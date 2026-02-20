# app/slices/customers/services.py
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps

from .mapper import (
    CustomerDashboardView,
    CustomerEligibilityView,
    map_customer_dashboard,
    map_customer_eligibility,
)
from .models import Customer, CustomerEligibility, CustomerHistory

"""
implement the customers.services_history.append_entry(...) function,
make it responsible for:

validating the envelope (not the payload),

populating the cached columns (title/summary/tags/has_admin_tags/...),

and enforcing “admin_tags never rendered” at the template layer.

That keeps the feature sturdy and boring.
"""
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

    row = CustomerEligibility(customer_entity_ulid=ent)  # type: ignore
    db.session.add(row)
    db.session.flush()
    return row


# -----------------
# Public reads
# -----------------


def get_eligibility_snapshot(
    entity_ulid: str,
) -> CustomerEligibilityView | None:
    ent = _ensure_entity_ulid(entity_ulid)

    row = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_entity_ulid == ent)
        .one_or_none()
    )
    if row is None:
        return None

    return map_customer_eligibility(row)


def get_dashboard_view(entity_ulid: str) -> CustomerDashboardView | None:
    ent = _ensure_entity_ulid(entity_ulid)

    cust = db.session.get(Customer, ent)
    if not cust:
        return None

    t1 = _latest_tier_map(ent, "tier1")
    t2 = _latest_tier_map(ent, "tier2")
    t3 = _latest_tier_map(ent, "tier3")

    return map_customer_dashboard(
        cust, {"tier1": t1, "tier2": t2, "tier3": t3}
    )


# -----------------
# Public commands
# -----------------


def tags_to_csv(tags: tuple[str, ...]) -> str | None:
    # Canon: stable ordering for deterministic diffs/tests.
    uniq = sorted(set(t for t in tags if t))
    if not uniq:
        return None
    return ",".join(uniq)


def csv_to_tags(csv: str | None) -> tuple[str, ...]:
    if not csv:
        return ()
    parts = [p.strip() for p in csv.split(",")]
    parts = [p for p in parts if p]
    return tuple(parts)


def append_history_entry(
    *,
    target_entity_ulid: str,
    kind: str,
    blob_json: str | dict[str, Any],
    actor_ulid: str | None,
    request_id: str | None,
) -> str:
    """
    Returns the new customer_history.history_ulid.
    Raises ContractError on validation failure.
    """


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
        entity_ulid=ent,  # type: ignore
        status="active",  # type: ignore
        intake_step=STEP_COMPLETE,  # type: ignore
        first_seen_utc=now,  # type: ignore
        last_touch_utc=now,  # type: ignore
        tier1_min=None,  # type: ignore
        tier2_min=None,  # type: ignore
        tier3_min=None,  # type: ignore
        flag_tier1_immediate=False,  # type: ignore
        flag_reason=None,  # type: ignore
        watchlist=False,  # type: ignore
        watchlist_since_utc=None,  # type: ignore
        last_needs_update_utc=None,  # type: ignore
        last_needs_tier_updated=None,  # type: ignore
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
        customer_entity_ulid=ent,  # type: ignore
        section=section,  # type: ignore
        version=version,  # type: ignore
        data_json=stable_dumps(norm),  # type: ignore
        created_by_actor=actor_ulid,  # type: ignore
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
) -> CustomerEligibilityView:
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


# Public exports
__all__ = [
    "get_eligibility_snapshot",
    "get_dashboard_view",
    "ensure_customer",
    "record_needs_tier",
    "set_veteran_verification",
]
