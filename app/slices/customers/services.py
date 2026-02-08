# app/slices/customers/services.py
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.extensions.contracts import entity_v2
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps

from .models import Customer, CustomerEligibility, CustomerHistory

# -----------------
# Canonical values (policy-backed later)
# -----------------

TIER_FACTORS: dict[str, tuple[str, ...]] = {
    "tier1": ("food", "hygiene", "health", "housing", "clothing"),
    "tier2": ("income", "employment", "transportation", "education"),
    "tier3": ("family", "peergroup", "tech"),
}
ALLOWED_VALUES = {1, 2, 3, "unknown", "n/a", None}

# Intake step order (canonical)
STEP_IDENTITY = "identity"
STEP_ADDR_PHYS = "address_physical"
STEP_ADDR_POST = "address_postal"
STEP_CONTACT = "contact"
STEP_ELIGIBILITY = "eligibility"
STEP_REVIEW = "review"
STEP_COMPLETE = "complete"


# -----------------
# Read projections (typed, PII-free)
# -----------------


@dataclass(frozen=True, slots=True)
class CustomerDashboardView:
    entity_ulid: str

    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None

    flag_tier1_immediate: bool
    flag_reason: str | None
    watchlist: bool
    watchlist_since_utc: str | None

    status: str
    intake_step: str | None

    first_seen_utc: str | None
    last_touch_utc: str | None
    last_needs_update_utc: str | None
    last_needs_tier_updated: str | None

    tier_factors: Mapping[str, Mapping[str, object]]
    as_of_iso: str


@dataclass(frozen=True, slots=True)
class CustomerEligibilitySnapshot:
    """PII-free eligibility snapshot anchored by entity_ulid."""

    entity_ulid: str

    is_veteran_verified: bool
    veteran_method: str | None
    approved_by_ulid: str | None
    approved_at_utc: str | None
    is_homeless_verified: bool

    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None

    notes: str | None

    created_at_utc: str | None
    updated_at_utc: str | None


# -----------------
# Helpers
# -----------------


def _ensure_request_id(request_id: str | None) -> str:
    rid = (request_id or "").strip()
    if not rid:
        raise ValueError("request_id must be non-empty")
    return rid


def _ensure_entity_ulid(entity_ulid: str | None) -> str:
    ent = (entity_ulid or "").strip()
    if not ent:
        raise ValueError("entity_ulid is required")
    return ent


def _validate_tier_payload(
    tier_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if tier_key not in TIER_FACTORS:
        raise ValueError(f"unknown tier '{tier_key}'")

    allowed = set(TIER_FACTORS[tier_key])
    extra = set(payload.keys()) - allowed
    if extra:
        raise ValueError(f"invalid factor(s) for {tier_key}: {sorted(extra)}")

    norm: dict[str, Any] = {}
    for factor in allowed:
        v = payload.get(factor)
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in ALLOWED_VALUES:
            raise ValueError(f"invalid value for {tier_key}.{factor}: {v!r}")
        norm[factor] = v
    return norm


def _min_numeric(d: dict[str, Any] | None) -> int | None:
    if not d:
        return None
    nums = [int(v) for v in d.values() if isinstance(v, int)]
    return min(nums) if nums else None


def _compute_cues(
    tier1: dict[str, Any] | None,
    tier2: dict[str, Any] | None,
    tier3: dict[str, Any] | None,
) -> tuple[int | None, int | None, int | None, bool, bool]:
    t1_min = _min_numeric(tier1)
    t2_min = _min_numeric(tier2)
    t3_min = _min_numeric(tier3)
    flag_t1 = t1_min == 1
    watch = t2_min == 1
    return t1_min, t2_min, t3_min, flag_t1, watch


def _first_worst_factor_tier1(tier1: dict[str, Any]) -> str | None:
    for f in TIER_FACTORS["tier1"]:
        v = tier1.get(f)
        if isinstance(v, int) and v == 1:
            return f"{f}=1"
    return None


def _latest_tier_map(entity_ulid: str, tier_key: str) -> dict[str, object]:
    section = f"profile:needs:{tier_key}"
    row = (
        db.session.query(CustomerHistory)
        .filter_by(customer_entity_ulid=entity_ulid, section=section)
        .order_by(desc(CustomerHistory.version))
        .first()
    )
    return json.loads(row.data_json) if row else {}


def _elig_row(entity_ulid: str) -> CustomerEligibility:
    """Get-or-create eligibility anchored by entity_ulid."""
    ent = _ensure_entity_ulid(entity_ulid)

    row = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_entity_ulid == ent)
        .one_or_none()
    )
    if row:
        return row

    row = CustomerEligibility(customer_entity_ulid=ent)
    db.session.add(row)
    db.session.flush()
    return row


# -----------------
# Public reads
# -----------------


def get_eligibility_snapshot(
    entity_ulid: str,
) -> CustomerEligibilitySnapshot | None:
    ent = _ensure_entity_ulid(entity_ulid)

    row = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_entity_ulid == ent)
        .one_or_none()
    )
    if row is None:
        return None

    def _g(name: str, default=None):
        return getattr(row, name, default)

    created = _g("created_at_utc", None) or _g("created_at", None)
    updated = _g("updated_at_utc", None) or _g("updated_at", None)

    return CustomerEligibilitySnapshot(
        entity_ulid=ent,
        is_veteran_verified=bool(_g("is_veteran_verified", False)),
        veteran_method=_g("veteran_method", None),
        approved_by_ulid=_g("approved_by_ulid", None),
        approved_at_utc=_g("approved_at_utc", None),
        is_homeless_verified=bool(_g("is_homeless_verified", False)),
        tier1_min=_g("tier1_min", None),
        tier2_min=_g("tier2_min", None),
        tier3_min=_g("tier3_min", None),
        notes=_g("notes", None),
        created_at_utc=created,
        updated_at_utc=updated,
    )


def get_dashboard_view(entity_ulid: str) -> CustomerDashboardView | None:
    ent = _ensure_entity_ulid(entity_ulid)

    cust = db.session.get(Customer, ent)
    if not cust:
        return None

    t1 = _latest_tier_map(ent, "tier1")
    t2 = _latest_tier_map(ent, "tier2")
    t3 = _latest_tier_map(ent, "tier3")

    return CustomerDashboardView(
        entity_ulid=ent,
        tier1_min=getattr(cust, "tier1_min", None),
        tier2_min=getattr(cust, "tier2_min", None),
        tier3_min=getattr(cust, "tier3_min", None),
        flag_tier1_immediate=bool(
            getattr(cust, "flag_tier1_immediate", False)
        ),
        flag_reason=getattr(cust, "flag_reason", None),
        watchlist=bool(getattr(cust, "watchlist", False)),
        watchlist_since_utc=getattr(cust, "watchlist_since_utc", None),
        status=getattr(cust, "status", ""),
        intake_step=getattr(cust, "intake_step", None),
        first_seen_utc=getattr(cust, "first_seen_utc", None),
        last_touch_utc=getattr(cust, "last_touch_utc", None),
        last_needs_update_utc=getattr(cust, "last_needs_update_utc", None),
        last_needs_tier_updated=getattr(
            cust, "last_needs_tier_updated", None
        ),
        tier_factors={"tier1": t1, "tier2": t2, "tier3": t3},
        as_of_iso=now_iso8601_ms(),
    )


# -----------------
# Public commands
# -----------------


def ensure_customer(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    _ensure_request_id(request_id)
    ent = _ensure_entity_ulid(entity_ulid)

    now = now_iso8601_ms()

    cust = db.session.get(Customer, ent)
    if cust:
        cust.last_touch_utc = now
        _elig_row(ent)
        db.session.flush()
        return ent

    cust = Customer(
        entity_ulid=ent,
        status="active",
        intake_step=STEP_COMPLETE,
        first_seen_utc=now,
        last_touch_utc=now,
        tier1_min=None,
        tier2_min=None,
        tier3_min=None,
        flag_tier1_immediate=False,
        flag_reason=None,
        watchlist=False,
        watchlist_since_utc=None,
        last_needs_update_utc=None,
        last_needs_tier_updated=None,
    )
    db.session.add(cust)

    _elig_row(ent)
    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="created",
        actor_ulid=actor_ulid,
        target_ulid=ent,
        request_id=request_id,
        happened_at_utc=now,
        refs={"entity_ulid": ent},
    )
    return ent


def record_needs_tier(
    *,
    entity_ulid: str,
    tier_key: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> str:
    """Write a tier snapshot (values live ONLY in History)."""
    _ensure_request_id(request_id)
    ent = _ensure_entity_ulid(entity_ulid)

    cust = db.session.get(Customer, ent)
    if not cust:
        raise LookupError("customer not found")

    norm = _validate_tier_payload(tier_key, payload)

    section = f"profile:needs:{tier_key}"
    cur_max = (
        db.session.query(func.max(CustomerHistory.version))
        .filter_by(customer_entity_ulid=ent, section=section)
        .scalar()
    )
    version = int(cur_max or 0) + 1

    hist = CustomerHistory(
        customer_entity_ulid=ent,
        section=section,
        version=version,
        data_json=stable_dumps(norm),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    latest_t1 = (
        _latest_tier_map(ent, "tier1") if tier_key != "tier1" else norm
    )
    latest_t2 = (
        _latest_tier_map(ent, "tier2") if tier_key != "tier2" else norm
    )
    latest_t3 = (
        _latest_tier_map(ent, "tier3") if tier_key != "tier3" else norm
    )

    t1_min, t2_min, t3_min, flag_t1, watch = _compute_cues(
        latest_t1, latest_t2, latest_t3
    )

    now = now_iso8601_ms()
    prev_watch = bool(getattr(cust, "watchlist", False))

    cust.tier1_min = t1_min
    cust.tier2_min = t2_min
    cust.tier3_min = t3_min
    cust.flag_tier1_immediate = flag_t1
    cust.flag_reason = (
        _first_worst_factor_tier1(latest_t1 or {}) if flag_t1 else None
    )

    cust.watchlist = watch
    if (
        watch
        and not prev_watch
        and not getattr(cust, "watchlist_since_utc", None)
    ):
        cust.watchlist_since_utc = now
    if not watch and prev_watch:
        cust.watchlist_since_utc = None

    cust.last_needs_update_utc = now
    cust.last_needs_tier_updated = tier_key
    cust.last_touch_utc = now

    elig = _elig_row(ent)
    elig.tier1_min = t1_min
    elig.tier2_min = t2_min
    elig.tier3_min = t3_min

    housing = (
        latest_t1.get("housing") if isinstance(latest_t1, dict) else None
    )
    elig.is_homeless_verified = bool(
        isinstance(housing, int) and housing == 1
    )

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="needs_tier_recorded",
        actor_ulid=actor_ulid,
        target_ulid=ent,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "section": section,
            "version_ptr": getattr(hist, "ulid", None),
        },
        changed={"fields": [tier_key]},
    )

    return getattr(hist, "ulid", "")


def set_veteran_verification(
    *,
    entity_ulid: str,
    method: str,
    verified: bool,
    actor_ulid: str | None,
    actor_has_governor: bool,
    request_id: str,
) -> CustomerEligibilitySnapshot:
    """Update eligibility verification fields (anchored by entity_ulid)."""
    _ensure_request_id(request_id)
    ent = _ensure_entity_ulid(entity_ulid)

    from app.extensions.contracts import governance_v2

    allowed = set(governance_v2.get_customer_veteran_verification_methods())
    if method not in allowed:
        raise ValueError(f"invalid veteran verification method: {method!r}")

    if method == "other" and not actor_has_governor:
        raise PermissionError("method 'other' requires governor authority")

    elig = _elig_row(ent)

    if verified:
        elig.is_veteran_verified = True
        elig.veteran_method = method
        if method == "other":
            elig.approved_by_ulid = actor_ulid
            elig.approved_at_utc = now_iso8601_ms()
    else:
        elig.is_veteran_verified = False
        elig.veteran_method = None
        elig.approved_by_ulid = None
        elig.approved_at_utc = None

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="veteran_verification_updated",
        actor_ulid=actor_ulid,
        target_ulid=ent,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"kind": "veteran"},
        changed={"fields": ["is_veteran_verified", "veteran_method"]},
    )

    snap = get_eligibility_snapshot(ent)
    if snap is None:
        raise RuntimeError("eligibility snapshot missing after update")
    return snap


# -----------------
# Intake (minimal; still contract-driven)
# -----------------


def intake_lookup(
    *,
    last_name: str,
    dob: str,
    last_4: str,
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    _ensure_request_id(request_id)

    ln = (last_name or "").strip()
    d = (dob or "").strip()
    l4 = (last_4 or "").strip()
    if not ln or not d or not l4:
        raise ValueError("last_name, dob, last_4 are required")

    matches = entity_v2.search_customer_candidates(
        db.session,
        last_name=ln,
        dob=d,
        last_4=l4,
    )

    ent_ids = [m.entity_ulid for m in matches]
    cust_by_entity: dict[str, Customer] = {}
    if ent_ids:
        rows = (
            db.session.query(Customer)
            .filter(Customer.entity_ulid.in_(ent_ids))
            .all()
        )
        cust_by_entity = {c.entity_ulid: c for c in rows}

    def _is_exact(m: entity_v2.MatchDTO) -> bool:
        if int(m.score or 0) >= 100:
            return True
        reasons = [str(r).lower() for r in (m.reasons or [])]
        return any("exact" in r for r in reasons)

    matches_sorted = sorted(
        matches,
        key=lambda m: int(m.score or 0),
        reverse=True,
    )

    candidates: list[dict[str, Any]] = []
    has_exact_match = False
    for m in matches_sorted:
        exact = _is_exact(m)
        has_exact_match = has_exact_match or exact
        c = cust_by_entity.get(m.entity_ulid)
        candidates.append(
            {
                "entity_ulid": m.entity_ulid,
                "score": int(m.score or 0),
                "reasons": list(m.reasons or []),
                "customer_exists": bool(c),
                "status": getattr(c, "status", None) if c else None,
                "intake_step": getattr(c, "intake_step", None) if c else None,
                "exact": exact,
            }
        )

    return {
        "matches": candidates,
        "has_exact_match": has_exact_match,
        "allow_start": not has_exact_match,
        "match_count": len(candidates),
    }


def intake_start(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str | None,
    dob: str,
    last_4: str,
    branch: str | None,
    era: str | None,
    request_id: str,
    actor_ulid: str | None,
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    _ensure_request_id(request_id)

    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    d = (dob or "").strip()
    l4 = (last_4 or "").strip()
    pn = (preferred_name or "").strip() or None

    if not fn or not ln:
        raise ValueError("first_name and last_name are required")
    if not d or not l4:
        raise ValueError("dob and last_4 are required")

    ent = entity_v2.create_customer_person(
        db.session,
        first_name=fn,
        last_name=ln,
        preferred_name=pn,
        dob=d,
        last_4=l4,
        branch=(branch or "").strip() or None,
        era=(era or "").strip() or None,
        request_id=request_id,
        actor_ulid=actor_ulid,
        allow_duplicate=bool(allow_duplicate),
    )
    entity_ulid = ent.entity_ulid

    now = now_iso8601_ms()
    cust = Customer(
        entity_ulid=entity_ulid,
        status="intake",
        intake_step=STEP_ADDR_PHYS,
        first_seen_utc=now,
        last_touch_utc=now,
    )
    db.session.add(cust)
    _elig_row(entity_ulid)
    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="intake_started",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        refs={"entity_ulid": entity_ulid},
        changed={"fields": ["status", "intake_step"]},
    )

    return {
        "entity_ulid": entity_ulid,
        "next_step": STEP_ADDR_PHYS,
    }
