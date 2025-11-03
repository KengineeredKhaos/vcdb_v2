# app/slices/customer/services.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from sqlalchemy import desc, func, select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps
from app.slices.entity.models import Entity

from .models import Customer, CustomerEligibility, CustomerHistory

"""
Homelessness is derived strictly from Tier-1 housing == 1,
and we sync that into CustomerEligibility automatically on every tier write.

record_needs_tier() is your single writer for tier data (History only)
and the denormalized cues; the three update_tierN() helpers wrap it.

Veteran verification is enforced: other requires a governor;
we never store images/PII—just the method and approver ULID for audit.

DashboardView is a single, cheap read that always reflects the latest rows;
it’s safe for UI and for quick CLI inspection.

Every write emits a minimal ledger event with only names/refs (no values),
matching Ledger ethos.
"""

# -----------------
# Canonical values
# -----------------

TIER_FACTORS: dict[str, tuple[str, ...]] = {
    "tier1": ("food", "hygiene", "health", "housing", "clothing"),
    "tier2": ("income", "employment", "transportation", "education"),
    "tier3": ("family", "peergroup", "tech"),
}
ALLOWED_VALUES = {1, 2, 3, "unknown", "n/a", None}
ALLOWED_METHODS = {"dd214", "va_id", "state_dl_veteran", "other"}

# -----------------
# Snapshots
# -----------------


@dataclass(frozen=True)
class EligibilitySnapshot:
    customer_ulid: str
    is_veteran_verified: bool
    is_homeless_verified: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    as_of_iso: str


@dataclass(frozen=True)
class DashboardView:
    # core ids
    customer_ulid: str
    entity_ulid: str
    # coarse needs
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    # flags/cues
    flag_tier1_immediate: bool
    flag_reason: str | None
    watchlist: bool
    watchlist_since_utc: str | None
    # qualifiers
    is_veteran_verified: bool
    veteran_method: str | None
    is_homeless_verified: bool
    # latest factor maps (denormalized for quick view; values are non-PII enums/ints)
    tier_factors: Mapping[str, Mapping[str, object]]
    # ops/status
    status: str
    first_seen_utc: str | None
    last_touch_utc: str | None
    last_needs_update_utc: str | None
    last_needs_tier_updated: str | None
    as_of_iso: str


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


def _first_worst_factor_tier1(tier1: dict[str, Any]) -> Optional[str]:
    for f in TIER_FACTORS["tier1"]:
        v = tier1.get(f)
        if isinstance(v, int) and v == 1:
            return f"{f}=1"
    return None


def _latest_tier_map(customer_ulid: str, tier_key: str) -> dict[str, object]:
    row = (
        db.session.query(CustomerHistory)
        .filter_by(
            customer_ulid=customer_ulid, section=f"profile:needs:{tier_key}"
        )
        .order_by(desc(CustomerHistory.version))
        .first()
    )
    return json.loads(row.data_json) if row else {}


def _elig_row(customer_ulid: str) -> CustomerEligibility:
    row = (
        db.session.query(CustomerEligibility)
        .filter_by(customer_ulid=customer_ulid)
        .first()
    )
    if not row:
        row = CustomerEligibility(customer_ulid=customer_ulid)
        db.session.add(row)
    return row


def _row_to_snapshot(row: CustomerEligibility) -> EligibilitySnapshot:
    return EligibilitySnapshot(
        customer_ulid=row.customer_ulid,
        is_veteran_verified=bool(row.is_veteran_verified),
        is_homeless_verified=bool(row.is_homeless_verified),
        tier1_min=row.tier1_min,
        tier2_min=row.tier2_min,
        tier3_min=row.tier3_min,
        as_of_iso=now_iso8601_ms(),
    )


# -----------------
# Public API (writes emit ledger)
# -----------------


def ensure_customer(
    *, entity_ulid: str, request_id: str, actor_ulid: Optional[str]
) -> str:
    """Idempotently ensure a Customer row exists for the given Entity; emit ledger on first create."""
    _ensure_reqid(request_id)

    if not db.session.get(Entity, entity_ulid):
        raise ValueError("entity not found")

    cust = (
        db.session.query(Customer).filter_by(entity_ulid=entity_ulid).first()
    )
    if not cust:
        now = now_iso8601_ms()
        cust = Customer(
            entity_ulid=entity_ulid, first_seen_utc=now, last_touch_utc=now
        )
        db.session.add(cust)
        db.session.commit()
        event_bus.emit(
            domain="customers",
            operation="profile_update",
            actor_ulid=actor_ulid,
            target_ulid=cust.ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"entity_ulid": entity_ulid},
        )
    else:
        cust.last_touch_utc = now_iso8601_ms()
        db.session.commit()

    return cust.ulid


def record_needs_tier(
    *,
    customer_ulid: str,
    tier_key: str,  # "tier1" | "tier2" | "tier3"
    payload: Dict[str, Any],  # factor values for that tier
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    """
    Store a new Needs snapshot for a single tier (values live ONLY in History).
    Updates Customer denormalized cues + Eligibility coarse mins & homeless flag.
    Emits a ledger event (no values).
    """
    _ensure_reqid(request_id)

    cust = db.session.get(Customer, customer_ulid)
    if not cust:
        raise ValueError("customer not found")

    norm = _validate_tier_payload(tier_key, payload)

    section = f"profile:needs:{tier_key}"
    cur_max = (
        db.session.query(func.max(CustomerHistory.version))
        .filter_by(customer_ulid=customer_ulid, section=section)
        .scalar()
    )
    version = int(cur_max or 0) + 1

    hist = CustomerHistory(
        customer_ulid=customer_ulid,
        section=section,
        version=version,
        data_json=stable_dumps(norm),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    # recompute latest maps for all tiers
    latest_t1 = (
        _latest_tier_map(customer_ulid, "tier1")
        if tier_key != "tier1"
        else norm
    )
    latest_t2 = (
        _latest_tier_map(customer_ulid, "tier2")
        if tier_key != "tier2"
        else norm
    )
    latest_t3 = (
        _latest_tier_map(customer_ulid, "tier3")
        if tier_key != "tier3"
        else norm
    )
    if tier_key == "tier1":
        latest_t1 = norm
    elif tier_key == "tier2":
        latest_t2 = norm
    else:
        latest_t3 = norm

    # compute cues
    t1_min, t2_min, t3_min, flag_t1, watch = _compute_operational_cues(
        latest_t1, latest_t2, latest_t3
    )

    # update Customer cues
    now = now_iso8601_ms()
    prev_watch = bool(cust.watchlist)
    cust.tier1_min = t1_min
    cust.tier2_min = t2_min
    cust.tier3_min = t3_min
    cust.flag_tier1_immediate = flag_t1
    cust.flag_reason = (
        _first_worst_factor_tier1(latest_t1 or {}) if flag_t1 else None
    )
    cust.watchlist = watch
    if watch and not prev_watch and not cust.watchlist_since_utc:
        cust.watchlist_since_utc = now
    if not watch and prev_watch:
        cust.watchlist_since_utc = None
    cust.last_needs_update_utc = now
    cust.last_needs_tier_updated = tier_key
    cust.last_touch_utc = now

    # update Eligibility (coarse mins + homeless derivation)
    elig = _elig_row(customer_ulid)
    elig.tier1_min, elig.tier2_min, elig.tier3_min = t1_min, t2_min, t3_min
    housing = (
        latest_t1.get("housing") if isinstance(latest_t1, dict) else None
    )
    elig.is_homeless_verified = bool(
        isinstance(housing, int) and housing == 1
    )

    db.session.commit()

    event_bus.emit(
        domain="customers",
        operation="profile_update",
        actor_ulid=actor_ulid,
        target_ulid=customer_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"section": section, "version_ptr": hist.ulid},
        changed={"fields": [tier_key]},
    )
    return hist.ulid


def update_tier1(
    *,
    customer_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    return record_needs_tier(
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
    return record_needs_tier(
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
    return record_needs_tier(
        customer_ulid=customer_ulid,
        tier_key="tier3",
        payload=payload,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def set_veteran_verification(
    *,
    customer_ulid: str,
    method: str,
    verified: bool,
    actor_ulid: str | None,
    actor_has_governor: bool,  # Governance check result
    request_id: str,
) -> EligibilitySnapshot:
    """
    Set/clear veteran verification and record method.
    Rule: method='other' requires actor with Domain role 'governor'.
    Emits ledger 'verification_updated'.
    """
    _ensure_reqid(request_id)
    method = (method or "").lower().strip()

    if verified and method not in ALLOWED_METHODS:
        raise ValueError(f"invalid method: {method!r}")
    if verified and method == "other" and not actor_has_governor:
        raise PermissionError("governor override required for method='other'")

    if not db.session.get(Customer, customer_ulid):
        raise ValueError("customer not found")

    row = _elig_row(customer_ulid)
    row.is_veteran_verified = bool(verified)
    if verified:
        row.veteran_method = method
        if method == "other":
            row.approved_by_ulid = actor_ulid
            row.approved_at_utc = now_iso8601_ms()
        else:
            row.approved_by_ulid = None
            row.approved_at_utc = None
    else:
        row.veteran_method = None
        row.approved_by_ulid = None
        row.approved_at_utc = None

    db.session.commit()

    event_bus.emit(
        domain="customers",
        operation="profile_update",
        actor_ulid=actor_ulid,
        target_ulid=customer_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed={"fields": ["is_veteran_verified", "veteran_method"]},
    )
    return _row_to_snapshot(row)


# -----------------
# Public API (reads)
# -----------------


def get_eligibility_snapshot(customer_ulid: str) -> EligibilitySnapshot:
    """
    Read-only coarse snapshot for Governance evaluation.
    Returns conservative defaults if row not created yet.
    """
    row = db.session.execute(
        select(CustomerEligibility).where(
            CustomerEligibility.customer_ulid == customer_ulid
        )
    ).scalar_one_or_none()

    if row is None:
        return EligibilitySnapshot(
            customer_ulid=customer_ulid,
            is_veteran_verified=False,
            is_homeless_verified=False,
            tier1_min=None,
            tier2_min=None,
            tier3_min=None,
            as_of_iso=now_iso8601_ms(),
        )
    return _row_to_snapshot(row)


def get_dashboard_view(customer_ulid: str) -> DashboardView | None:
    """
    Fast, get-only dashboard view composed from:
    - Customer (cues/ops)
    - CustomerEligibility (coarse qualifiers)
    - Latest tier factor maps from History
    """
    c = db.session.get(Customer, customer_ulid)
    if not c:
        return None

    elig = (
        db.session.query(CustomerEligibility)
        .filter_by(customer_ulid=customer_ulid)
        .first()
    )

    # Pull latest factor maps for each tier
    t1 = _latest_tier_map(customer_ulid, "tier1")
    t2 = _latest_tier_map(customer_ulid, "tier2")
    t3 = _latest_tier_map(customer_ulid, "tier3")

    return DashboardView(
        customer_ulid=c.ulid,
        entity_ulid=c.entity_ulid,
        tier1_min=c.tier1_min,
        tier2_min=c.tier2_min,
        tier3_min=c.tier3_min,
        flag_tier1_immediate=c.flag_tier1_immediate,
        flag_reason=c.flag_reason,
        watchlist=c.watchlist,
        watchlist_since_utc=c.watchlist_since_utc,
        is_veteran_verified=bool(elig.is_veteran_verified) if elig else False,
        veteran_method=elig.veteran_method if elig else None,
        is_homeless_verified=bool(elig.is_homeless_verified)
        if elig
        else False,
        tier_factors={"tier1": t1, "tier2": t2, "tier3": t3},
        status=c.status,
        first_seen_utc=c.first_seen_utc,
        last_touch_utc=c.last_touch_utc,
        last_needs_update_utc=c.last_needs_update_utc,
        last_needs_tier_updated=c.last_needs_tier_updated,
        as_of_iso=now_iso8601_ms(),
    )
