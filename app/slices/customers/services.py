# app/slices/customers/services.py
from __future__ import annotations

from dataclasses import dataclass

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from sqlalchemy import desc, func, select

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

INTAKE_STEP_COMPLETE = "complete"


# -----------------
# Snapshots
# -----------------


@dataclass(frozen=True)
class DashboardView:
    ulid: str  # NOTE: keep "ulid" for route/test friendliness
    customer_ulid: str
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


# -----------------
# Helpers
# -----------------


@dataclass(frozen=True, slots=True)
class CustomerEligibilitySnapshot:
    """PII-free eligibility snapshot anchored by customer_ulid.

    This is the canonical typed snapshot consumed by contracts and routes.
    Do NOT treat ulid as an anchor; it is for ordering/debugging only.
    """

    ulid: str | None
    customer_ulid: str

    # Verification
    is_veteran_verified: bool
    veteran_method: str | None
    approved_by_ulid: str | None
    approved_at_utc: str | None
    is_homeless_verified: bool

    # Needs-derived mins (may be None until computed)
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None

    # Optional admin notes (PII-free)
    notes: str | None

    created_at_utc: str | None
    updated_at_utc: str | None


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
    """
    Get-or-create the eligibility row anchored by customer_ulid.
    NOTE: We do NOT key off CustomerEligibility.ulid.
    """
    cust = (customer_ulid or "").strip()
    if not cust:
        raise ValueError("customer_ulid is required")

    row = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == cust)
        .one_or_none()
    )
    if row:
        return row

    # IMPORTANT: do NOT pass bogus kwargs (e.g. status=...) unless the model has them.
    row = CustomerEligibility(customer_ulid=cust)
    db.session.add(row)
    db.session.flush()
    return row


def get_eligibility_snapshot(
    customer_ulid: str,
) -> CustomerEligibilitySnapshot | None:
    """
    Typed eligibility snapshot for UI/routes/contracts.

    IMPORTANT:
      - CustomerEligibility is NOT the home of Entity person vitals (branch/era/dob/last4).
        Those live in the Entity slice and must be accessed via entity_v2.
      - Anchored by customer_ulid (== entity_ulid by convention).
      - Schema-tolerant: never raise AttributeError due to missing optional columns.

    Returns None if no eligibility row exists.
    """
    cust = (customer_ulid or "").strip()
    if not cust:
        raise ValueError("customer_ulid is required")

    row = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == cust)
        .one_or_none()
    )
    if row is None:
        return None

    def _g(name: str, default=None):
        return getattr(row, name, default)

    created = _g("created_at_utc", None) or _g("created_at", None)
    updated = _g("updated_at_utc", None) or _g("updated_at", None)

    return CustomerEligibilitySnapshot(
        ulid=_g("ulid", None),
        customer_ulid=row.customer_ulid,
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


def ensure_customer(
    *, entity_ulid: str, request_id: str, actor_ulid: str | None
) -> str:
    ent = (entity_ulid or "").strip()
    if not ent:
        raise ValueError("entity_ulid is required")

    now = now_iso8601_ms()

    cust = db.session.get(Customer, ent)
    if cust:
        cust.last_touch_utc = now
        _ensure_customer_eligibility(customer_ulid=cust.ulid)
        db.session.flush()
        return cust.ulid
    cust = Customer(
        ulid=ent,
        entity_ulid=ent,
        status="active",
        intake_step=INTAKE_STEP_COMPLETE,
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

    # IMPORTANT: eligibility is anchored to customer_ulid, not its own ULID.
    _ensure_customer_eligibility(customer_ulid=cust.ulid)

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="created_insert",
        actor_ulid=actor_ulid,
        target_ulid=cust.ulid,
        request_id=request_id,
        happened_at_utc=now,
        refs={"entity_ulid": ent},
    )
    return cust.ulid


def set_veteran_verification(
    *,
    customer_ulid: str,
    method: str,
    verified: bool,
    actor_ulid: str | None,
    actor_has_governor: bool,
    request_id: str,
) -> CustomerEligibilitySnapshot:
    """
    Set (or clear) veteran verification on the eligibility row anchored by customer_ulid.

    Verification methods are governed by Governance policy (policy_customer.json) and
    must be consulted via governance_v2 contract.

    Contract/caller may additionally enforce:
      - method 'other' requires actor_has_governor=True (kept here as defense-in-depth)

    Returns:
        Eligibility snapshot dict compatible with customers_v2 contract expectations.
    """
    _ensure_reqid(request_id)

    cust = (customer_ulid or "").strip()
    if not cust:
        raise ValueError("customer_ulid is required")

    # Pull allowed methods from Governance policy via contract.
    # Local import avoids contract import cycles.
    from app.extensions.contracts import governance_v2

    allowed = set(governance_v2.get_customer_veteran_verification_methods())
    if method not in allowed:
        raise ValueError(f"invalid veteran verification method: {method!r}")

    if method == "other" and not actor_has_governor:
        raise PermissionError("method 'other' requires governor authority")

    elig = _elig_row(cust)

    if verified:
        elig.is_veteran_verified = True
        # method stored only when verified=True
        elig.veteran_method = method
        # approval fields are meaningful only for 'other' (policy exception)
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
        operation="verification_updated",
        actor_ulid=actor_ulid,
        target_ulid=cust,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"kind": "veteran"},
        changed={"fields": ["is_veteran_verified", "veteran_method"]},
    )

    snap = get_eligibility_snapshot(cust)
    if snap is None:
        # Should not happen because _elig_row creates the row.
        raise RuntimeError("eligibility snapshot missing after update")
    return snap


def _ensure_customer_eligibility(*, customer_ulid: str) -> None:
    exists = (
        db.session.query(CustomerEligibility.ulid)
        .filter(CustomerEligibility.customer_ulid == customer_ulid)
        .first()
    )
    if exists:
        return

    elig = CustomerEligibility(
        customer_ulid=customer_ulid,
        is_veteran_verified=False,
        veteran_method=None,
        approved_by_ulid=None,
        approved_at_utc=None,
        is_homeless_verified=False,
        tier1_min=None,
        tier2_min=None,
        tier3_min=None,
    )
    db.session.add(elig)


def record_needs_tier(
    *,
    customer_ulid: str,
    tier_key: str,
    payload: Dict[str, Any],
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
        raise LookupError("customer not found")

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

    # compute cues
    t1_min, t2_min, t3_min, flag_t1, watch = _compute_operational_cues(
        latest_t1, latest_t2, latest_t3
    )

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

    elig = _elig_row(customer_ulid)
    elig.tier1_min, elig.tier2_min, elig.tier3_min = t1_min, t2_min, t3_min

    housing = (
        latest_t1.get("housing") if isinstance(latest_t1, dict) else None
    )
    elig.is_homeless_verified = bool(
        isinstance(housing, int) and housing == 1
    )

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="profile_update",
        actor_ulid=actor_ulid,
        target_ulid=customer_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"section": section, "version_ptr": getattr(hist, "ulid", None)},
        changed={"fields": [tier_key]},
    )
    return getattr(hist, "ulid", "")


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


# -----------------
# Public API (reads)
# -----------------


def get_dashboard_view(customer_ulid: str) -> DashboardView | None:
    c = db.session.get(Customer, customer_ulid)
    if not c:
        return None

    t1 = _latest_tier_map(customer_ulid, "tier1")
    t2 = _latest_tier_map(customer_ulid, "tier2")
    t3 = _latest_tier_map(customer_ulid, "tier3")

    return DashboardView(
        ulid=c.ulid,
        customer_ulid=c.ulid,
        entity_ulid=c.entity_ulid,
        tier1_min=c.tier1_min,
        tier2_min=c.tier2_min,
        tier3_min=c.tier3_min,
        flag_tier1_immediate=bool(c.flag_tier1_immediate),
        flag_reason=c.flag_reason,
        watchlist=bool(c.watchlist),
        watchlist_since_utc=c.watchlist_since_utc,
        status=c.status,
        intake_step=getattr(c, "intake_step", None),
        first_seen_utc=c.first_seen_utc,
        last_touch_utc=c.last_touch_utc,
        last_needs_update_utc=c.last_needs_update_utc,
        last_needs_tier_updated=c.last_needs_tier_updated,
        tier_factors={"tier1": t1, "tier2": t2, "tier3": t3},
        as_of_iso=now_iso8601_ms(),
    )


def customer_view(customer_ulid: str) -> dict[str, Any] | None:
    """
    JSON-friendly wrapper for routes/templates.
    Smoke tests expect "ulid" key.
    """
    dv = get_dashboard_view(customer_ulid)
    if not dv:
        return None
    d = asdict(dv)
    # alias for tests/UI
    d["ulid"] = dv.customer_ulid
    return d


# -----------------
# Intake Wizard Services (Step 0/1)
# -----------------


def intake_lookup(
    *,
    last_name: str,
    dob: str,
    last_4: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict[str, Any]:
    """
    Step 0: ask Entity slice for candidates by invariants.
    Return allow_start bool for UI gating.
    """
    _ensure_reqid(request_id)

    ln = (last_name or "").strip()
    d = (dob or "").strip()
    l4 = (last_4 or "").strip()
    if not ln or not d or not l4:
        raise ValueError("last_name, dob, last_4 are required")

    matches = entity_v2.search_customer_candidates(
        db.session, last_name=ln, dob=d, last_4=l4
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
        matches, key=lambda m: int(m.score or 0), reverse=True
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
                "customer_ulid": c.ulid if c else None,
                "score": int(m.score or 0),
                "reasons": list(m.reasons or []),
                "status": c.status if c else None,
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
    preferred_name: Optional[str],
    dob: str,
    last_4: str,
    branch: str | None,
    era: str | None,
    request_id: str,
    actor_ulid: Optional[str],
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    """
    Step 1: create Entity person (PII) via contract, then create Customer shell.
    """
    _ensure_reqid(request_id)

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
        ulid=entity_ulid,
        entity_ulid=entity_ulid,
        status="intake",
        intake_step=STEP_ADDR_PHYS,
        first_seen_utc=now,
        last_touch_utc=now,
    )
    db.session.add(cust)
    _elig_row(cust.ulid)
    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="intake_started",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=cust.ulid,
        refs={"entity_ulid": entity_ulid},
        changed={"fields": ["status", "intake_step"]},
    )

    return {
        "customer_ulid": cust.ulid,
        "entity_ulid": entity_ulid,
        "next_step": STEP_ADDR_PHYS,
    }
