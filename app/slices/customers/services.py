# app/slices/customers/services.py
from __future__ import annotations

from typing import Optional, Dict, Any, Tuple
import json

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps
from app.slices.entity.models import Entity

from .models import Customer, CustomerHistory

# ---------------------------------------------------------------------------
# Canonical tier/factor map per MVP (move to Governance later)
# ---------------------------------------------------------------------------
TIER_FACTORS: dict[str, tuple[str, ...]] = {
    "tier1": ("food", "hygiene", "health", "housing", "clothing"),
    "tier2": ("income", "employment", "transportation", "education"),
    "tier3": ("family", "peergroup", "tech"),
}

ALLOWED_VALUES = {1, 2, 3, "unknown", "n/a", None}


# ---- helpers ---------------------------------------------------------------


def _ensure_reqid(rid: Optional[str]) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid)


def _validate_tier_payload(
    tier_key: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    if tier_key not in TIER_FACTORS:
        raise ValueError(f"unknown tier '{tier_key}'")
    allowed = set(TIER_FACTORS[tier_key])
    extra = set(payload.keys()) - allowed
    if extra:
        raise ValueError(f"invalid factor(s) for {tier_key}: {sorted(extra)}")

    norm: Dict[str, Any] = {}
    for factor in allowed:
        v = payload.get(factor, None)
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in ALLOWED_VALUES:
            raise ValueError(f"invalid value for {tier_key}.{factor}: {v!r}")
        norm[factor] = v
    return norm


def _min_numeric(d: Optional[Dict[str, Any]]) -> Optional[int]:
    if not d:
        return None
    nums = [int(v) for v in d.values() if isinstance(v, int)]
    return min(nums) if nums else None


def _compute_operational_cues(
    tier1: Optional[Dict[str, Any]],
    tier2: Optional[Dict[str, Any]],
    tier3: Optional[Dict[str, Any]],
) -> Tuple[Optional[int], Optional[int], Optional[int], bool, bool]:
    t1_min = _min_numeric(tier1)
    t2_min = _min_numeric(tier2)
    t3_min = _min_numeric(tier3)
    flag_t1 = t1_min == 1
    watch = t2_min == 1
    return t1_min, t2_min, t3_min, flag_t1, watch


def _next_version(customer_ulid: str, section: str) -> int:
    cur = (
        db.session.query(func.max(CustomerHistory.version))
        .filter_by(customer_ulid=customer_ulid, section=section)
        .scalar()
    )
    return int(cur or 0) + 1


def _first_worst_factor_tier1(tier1: dict[str, Any]) -> Optional[str]:
    """
    Deterministic reason for flag: first factor in canonical order that equals 1.
    Returns e.g. 'food=1' or None.
    """
    if not tier1:
        return None
    for f in TIER_FACTORS["tier1"]:
        v = tier1.get(f)
        if isinstance(v, int) and v == 1:
            return f"{f}=1"
    return None


# ---- core API --------------------------------------------------------------


def ensure_customer(
    *, entity_ulid: str, request_id: str, actor_id: Optional[str]
) -> str:
    """Idempotently ensure a Customer record exists for the given Entity."""
    _ensure_reqid(request_id)

    if not db.session.get(Entity, entity_ulid):
        raise ValueError("entity not found")

    cust = (
        db.session.query(Customer).filter_by(entity_ulid=entity_ulid).first()
    )
    if not cust:
        now = now_iso8601_ms()
        cust = Customer(
            entity_ulid=entity_ulid,
            first_seen_utc=now,
            last_touch_utc=now,
        )
        db.session.add(cust)
        db.session.commit()
        event_bus.emit(
            type="customer.created",
            slice="customers",
            operation="insert",
            actor_id=actor_id,
            target_id=cust.ulid,
            request_id=request_id,
            happened_at=now,
            refs={"entity_ulid": entity_ulid},
        )
    else:
        # touch on ensure to mark activity if desired
        cust.last_touch_utc = now_iso8601_ms()
        db.session.commit()

    return cust.ulid


def update_needs_tier(
    *,
    customer_ulid: str,
    tier_key: str,  # "tier1" | "tier2" | "tier3"
    payload: Dict[str, Any],  # factor values for that tier
    request_id: str,
    actor_id: Optional[str],
) -> str:
    """
    Store a new Needs Assessment snapshot for a single tier (History-only values).
    Updates denormalized cues + ops fields; emits minimal ledger event.
    """
    _ensure_reqid(request_id)

    cust = db.session.get(Customer, customer_ulid)
    if not cust:
        raise ValueError("customer not found")

    norm = _validate_tier_payload(tier_key, payload)

    section = f"profile:needs:{tier_key}"
    version = _next_version(customer_ulid, section)
    hist = CustomerHistory(
        customer_ulid=customer_ulid,
        section=section,
        version=version,
        data_json=stable_dumps(norm),
        created_by_actor=actor_id,
    )
    db.session.add(hist)

    # recompute cues from latest per tier
    latest: dict[str, dict] = {}
    for tk in ("tier1", "tier2", "tier3"):
        h = (
            db.session.query(CustomerHistory)
            .filter_by(
                customer_ulid=customer_ulid, section=f"profile:needs:{tk}"
            )
            .order_by(desc(CustomerHistory.version))
            .first()
        )
        latest[tk] = json.loads(h.data_json) if h else {}

    t1_min, t2_min, t3_min, flag_t1, watch = _compute_operational_cues(
        latest.get("tier1"), latest.get("tier2"), latest.get("tier3")
    )

    cust.tier1_min = t1_min
    cust.tier2_min = t2_min
    cust.tier3_min = t3_min

    # watchlist_since_utc management
    prev_watch = bool(cust.watchlist)
    cust.watchlist = watch
    now = now_iso8601_ms()
    if watch and not prev_watch and not cust.watchlist_since_utc:
        cust.watchlist_since_utc = now
    if not watch and prev_watch:
        cust.watchlist_since_utc = None

    # flag management + reason (Tier1 only)
    cust.flag_tier1_immediate = flag_t1
    cust.flag_reason = (
        _first_worst_factor_tier1(latest.get("tier1") or {})
        if flag_t1
        else None
    )

    # ops helpers
    cust.last_needs_update_utc = now
    cust.last_needs_tier_updated = tier_key
    cust.last_touch_utc = now

    db.session.commit()

    # Minimal ledger event; no values — only the section & pointer
    event_bus.emit(
        type="customer.profile.updated",
        slice="customers",
        operation="update",
        actor_id=actor_id,
        target_id=customer_ulid,
        request_id=request_id,
        happened_at=now,
        changed_fields=["tierN"],
        refs={"section": section, "version_ptr": hist.ulid},
    )
    return hist.ulid


# convenience wrappers


def update_tier1(
    *,
    customer_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_id: Optional[str],
) -> str:
    return update_needs_tier(
        customer_ulid=customer_ulid,
        tier_key="tier1",
        payload=payload,
        request_id=request_id,
        actor_id=actor_id,
    )


def update_tier2(
    *,
    customer_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_id: Optional[str],
) -> str:
    return update_needs_tier(
        customer_ulid=customer_ulid,
        tier_key="tier2",
        payload=payload,
        request_id=request_id,
        actor_id=actor_id,
    )


def update_tier3(
    *,
    customer_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_id: Optional[str],
) -> str:
    return update_needs_tier(
        customer_ulid=customer_ulid,
        tier_key="tier3",
        payload=payload,
        request_id=request_id,
        actor_id=actor_id,
    )


# dashboard-friendly view


def customer_view(customer_ulid: str) -> Optional[dict]:
    c = db.session.get(Customer, customer_ulid)
    if not c:
        return None
    return {
        "customer_ulid": c.ulid,
        "entity_ulid": c.entity_ulid,
        "tier1_min": c.tier1_min,
        "tier2_min": c.tier2_min,
        "tier3_min": c.tier3_min,
        "flag_tier1_immediate": c.flag_tier1_immediate,
        "flag_reason": c.flag_reason,
        "watchlist": c.watchlist,
        "watchlist_since_utc": c.watchlist_since_utc,
        "status": c.status,
        "first_seen_utc": c.first_seen_utc,
        "last_touch_utc": c.last_touch_utc,
        "last_needs_update_utc": c.last_needs_update_utc,
        "last_needs_tier_updated": c.last_needs_tier_updated,
        "created_at_utc": c.created_at_utc,
        "updated_at_utc": c.updated_at_utc,
    }
