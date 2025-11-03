# app/slices/customers/services.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import desc, func, select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps
from app.slices.entity.models import Entity

from .models import Customer, CustomerEligibility, CustomerHistory

# ---------------------------------------------------------------------------
# Canonical tier/factor map per MVP (move to Governance later)
# ---------------------------------------------------------------------------
TIER_FACTORS: dict[str, tuple[str, ...]] = {
    "tier1": ("food", "hygiene", "health", "housing", "clothing"),
    "tier2": ("income", "employment", "transportation", "education"),
    "tier3": ("family", "peergroup", "tech"),
}

ALLOWED_VALUES = {1, 2, 3, "unknown", "n/a", None}

# -----------------
# Snapshot framing
# -----------------


@dataclass
class EligibilitySnapshot:
    is_veteran_verified: bool
    is_homeless_verified: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None


# -----------------
# helpers
# -----------------


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
    *, entity_ulid: str, request_id: str, actor_ulid: Optional[str]
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
            domain="customers",
            operation="created_insert",
            actor_ulid=actor_ulid,
            target_ulid=cust.ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
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
    actor_ulid: Optional[str],
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
        created_by_actor=actor_ulid,
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
        domain="customers",
        operation="profile_update",
        actor_ulid=actor_ulid,
        target_ulid=customer_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
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
    actor_ulid: Optional[str],
) -> str:
    return update_needs_tier(
        customer_ulid=customer_ulid,
        tier_key="tier1",
        payload=payload,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def update_tier2(
    *,
    customer_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    return update_needs_tier(
        customer_ulid=customer_ulid,
        tier_key="tier2",
        payload=payload,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def update_tier3(
    *,
    customer_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    return update_needs_tier(
        customer_ulid=customer_ulid,
        tier_key="tier3",
        payload=payload,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


# -----------------
# dashboard-friendly view
# -----------------


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


# -----------------
# Customer Eligibility
# -----------------
from typing import TYPE_CHECKING  # noqa: E402

from sqlalchemy import select  # noqa: E402

if TYPE_CHECKING:
    # Type-only import (won't execute at runtime)
    from app.extensions.contracts.customer_v2 import (
        CustomerEligibilitySnapshot,
    )


def _row_to_snapshot(row: CustomerEligibility):
    # Lazy import avoids contract ↔ provider circular imports
    from app.extensions.contracts.customer_v2 import (
        CustomerEligibilitySnapshot,
    )

    return CustomerEligibilitySnapshot(
        customer_ulid=row.customer_ulid,
        is_veteran_verified=bool(row.is_veteran_verified),
        is_homeless_verified=bool(row.is_homeless_verified),
        tier1_min=row.tier1_min,
        tier2_min=row.tier2_min,
        tier3_min=row.tier3_min,
        as_of_iso=now_iso8601_ms(),
    )


def get_eligibility_snapshot(customer_ulid: str) -> EligibilitySnapshot:
    """
    Read-only snapshot for policy evaluation.
    DO NOT create rows here; intake/update flows own writes.
    """
    row = db.session.execute(
        select(CustomerEligibility).where(
            CustomerEligibility.customer_ulid == customer_ulid
        )
    ).scalar_one_or_none()

    if row is None:
        # Ephemeral defaults for policy checks when no record exists yet.
        # Keep this conservative and documented.
        return EligibilitySnapshot(
            is_veteran_verified=False,
            is_homeless_verified=False,
            tier1_min=None,
            tier2_min=None,
            tier3_min=None,
        )

    return EligibilitySnapshot(
        is_veteran_verified=bool(row.is_veteran_verified),
        is_homeless_verified=bool(row.is_homeless_verified),
        tier1_min=row.tier1_min,
        tier2_min=row.tier2_min,
        tier3_min=row.tier3_min,
    )


def set_verification_flags(
    customer_ulid: str,
    *,
    veteran: bool | None = None,
    homeless: bool | None = None,
) -> "CustomerEligibilitySnapshot":
    row = db.session.execute(
        select(CustomerEligibility).where(
            CustomerEligibility.customer_ulid == customer_ulid
        )
    ).scalar_one_or_none()
    if row is None:
        row = CustomerEligibility(customer_ulid=customer_ulid)
        db.session.add(row)
    if veteran is not None:
        row.is_veteran_verified = bool(veteran)
    if homeless is not None:
        row.is_homeless_verified = bool(homeless)
    db.session.commit()
    return _row_to_snapshot(row)


def set_tier_min(
    customer_ulid: str,
    *,
    tier1: int | None = None,
    tier2: int | None = None,
    tier3: int | None = None,
) -> "CustomerEligibilitySnapshot":
    for name, val in (("tier1", tier1), ("tier2", tier2), ("tier3", tier3)):
        if val is not None and val not in (1, 2, 3):
            raise ValueError(f"{name} must be 1,2,3 or None")
    row = db.session.execute(
        select(CustomerEligibility).where(
            CustomerEligibility.customer_ulid == customer_ulid
        )
    ).scalar_one_or_none()
    if row is None:
        row = CustomerEligibility(customer_ulid=customer_ulid)
        db.session.add(row)
    if tier1 is not None:
        row.tier1_min = tier1
    if tier2 is not None:
        row.tier2_min = tier2
    if tier3 is not None:
        row.tier3_min = tier3
    db.session.commit()
    return _row_to_snapshot(row)
