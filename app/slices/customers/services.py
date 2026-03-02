# app/slices/customers/services.py
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import (
    ensure_actor_ulid,
    ensure_entity_ulid,
    ensure_request_id,
)
from app.lib.jsonutil import stable_dumps
from app.lib.pagination import Page, paginate

from .mapper import (
    AdminInboxItemRow,
    AdminInboxItemView,
    ChangeSetDTO,
    CustomerDashboardRow,
    CustomerDashboardView,
    CustomerEligibilityRow,
    CustomerEligibilityView,
    CustomerHistoryDetailRow,
    CustomerHistoryDetailView,
    CustomerHistoryItemRow,
    CustomerHistoryItemView,
    CustomerSummaryRow,
    CustomerSummaryView,
    EnvelopeDTO,
    ParsedHistoryBlobDTO,
    map_admin_inbox_item,
    map_customer_dashboard,
    map_customer_eligibility,
    map_customer_history_detail,
    map_customer_history_item,
    map_customer_summary,
)
from .models import (
    Customer,
    CustomerEligibility,
    CustomerHistory,
    CustomerProfile,
    CustomerProfileRating,
)
from .taxonomy import (
    BRANCH,
    ERA,
    HOMELESS_STATUS,
    INTAKE_STEPS,
    NEEDS_CATEGORY_KEY,
    RANK,
    RATING_ALLOWED,
    TIER1,
    TIER2,
    TIER3,
    VETERAN_METHOD,
    VETERAN_STATUS,
)

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


# Intake step order (canonical)

STEP_INTAKE = INTAKE_STEPS
STEP_ASSESSMENT = (
    "needs_begin",
    "needs_tier1",
    "needs_tier2",
    "needs_tier3",
)
STEP_ELIGIBILITY = "eligibility"
STEP_REVIEW = "review"
STEP_COMPLETE = "complete"


# -----------------
# Helper Functions
# & Validators
# -----------------


def _require_one_of(
    field: str, value: str | None, allowed: tuple[str, ...]
) -> str:
    v = (value or "").strip()
    if not v or v not in allowed:
        raise ValueError(f"invalid {field}: {value!r}")
    return v


def _require_nullable_one_of(
    field: str,
    value: str | None,
    allowed: tuple[str, ...],
) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if v not in allowed:
        raise ValueError(f"invalid {field}: {value!r}")
    return v


def _norm(s: str | None) -> str | None:
    if s is None:
        return None
    v = s.strip()
    return v if v else None


def _tier_min_for(
    ratings_by_key: dict[str, str],
    keys: tuple[str, ...],
) -> int | None:
    ranks: list[int] = []
    for k in keys:
        v = ratings_by_key.get(k, "na")
        r = RANK.get(v)
        if r is not None:
            ranks.append(r)
    return min(ranks) if ranks else None


def _min_numeric(d: dict[str, Any] | None) -> int | None:
    if not d:
        return None
    nums = [int(v) for v in d.values() if isinstance(v, int)]
    return min(nums) if nums else None


def _set_intake_step(c: Customer, step: str, changed: list[str]) -> None:
    step_key = str(step or "").strip().lower()
    if step_key not in INTAKE_STEPS:
        raise ValueError(f"invalid intake_step: {step!r}")

    prev = (c.intake_step or "").strip().lower()
    if prev != step_key:
        c.intake_step = step_key
        changed.append("customer.intake_step")


def get_current_needs_ratings(entity_ulid: str) -> dict[str, str]:
    ent = ensure_entity_ulid(entity_ulid)
    p = db.session.get(CustomerProfile, ent)
    if p is None or p.assessment_version < 1:
        return {}

    stmt = (
        select(
            CustomerProfileRating.category_key,
            CustomerProfileRating.rating_value,
        )
        .where(CustomerProfileRating.entity_ulid == ent)
        .where(
            CustomerProfileRating.assessment_version == p.assessment_version
        )
    )
    rows = db.session.execute(stmt).all()
    return dict(rows)


# -----------------
# Internal DTOs
# -----------------


@dataclass(frozen=True, slots=True)
class CustomerOverviewVM:
    entity_ulid: str
    display_name: str
    dash: CustomerDashboardView
    elig: CustomerEligibilityView
    ratings: dict[str, str]
    reassess_due: bool


# -----------------
# Display Name Builder
# -----------------


def _uniq_entity_ulids(entity_ulids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in entity_ulids:
        u2 = ensure_entity_ulid(u)
        if u2 not in seen:
            seen.add(u2)
            out.append(u2)
    return out


def get_entity_display_names(entity_ulids: list[str]) -> dict[str, str]:
    """
    Batch label hydration for UI (PII stays in Entity; not persisted here).

    Uses entity_v2 name-cards contract:
      get_entity_name_cards(list[str]) -> list[EntityNameCardDTO]
    """
    ulids = _uniq_entity_ulids(entity_ulids)
    if not ulids:
        return {}

    try:
        from app.extensions.contracts import entity_v2  # type: ignore
    except Exception:
        # Allow Customers slice to run even if Entity contract isn't wired yet.
        return {}

    try:
        cards: Any = entity_v2.get_entity_name_cards(ulids)
    except Exception:
        return {}

    out: dict[str, str] = {}
    for c in cards or []:
        u = getattr(c, "entity_ulid", None)
        name = getattr(c, "display_name", None)
        if not u:
            continue
        out[str(u)] = str(name) if name else str(u)
    return out


def get_entity_display_name(entity_ulid: str) -> str:
    ent = ensure_entity_ulid(entity_ulid)
    d = get_entity_display_names([ent])
    return d.get(ent, ent)


def list_customer_summaries_with_labels(
    *, page: int, per_page: int
) -> tuple[Page[CustomerSummaryView], dict[str, str]]:
    p = list_customer_summaries(page=page, per_page=per_page)
    ulids = [v.entity_ulid for v in p.items]
    labels = get_entity_display_names(ulids)
    return p, labels


# -----------------
# View/List/Summary
# -----------------


def _summary_stmt():
    return (
        select(Customer, CustomerEligibility)
        .outerjoin(
            CustomerEligibility,
            CustomerEligibility.entity_ulid == Customer.entity_ulid,
        )
        .order_by(Customer.entity_ulid.desc())
    )


def _tuple_to_summary_row(
    t: tuple[Customer, CustomerEligibility | None],
) -> CustomerSummaryRow:
    c, e = t
    return CustomerSummaryRow(
        entity_ulid=c.entity_ulid,
        status=c.status,
        intake_step=c.intake_step,
        intake_completed_at_iso=c.intake_completed_at_iso,
        needs_state=c.needs_state,
        tier1_min=c.tier1_min,
        flag_tier1_immediate=bool(c.flag_tier1_immediate),
        watchlist=bool(c.watchlist),
        veteran_status=(e.veteran_status if e else "unknown"),
    )


def list_customer_summaries(
    *, page: int, per_page: int
) -> Page[CustomerSummaryView]:
    # Page[tuple]
    p0 = paginate(_summary_stmt(), page=page, per_page=per_page)

    # Page[View]
    return p0.map(_tuple_to_summary_row).map(map_customer_summary)


def get_customer_summary(entity_ulid: str) -> CustomerSummaryView:
    stmt = _summary_stmt().where(Customer.entity_ulid == entity_ulid)
    row = db.session.execute(stmt).first()
    if row is None:
        raise LookupError("customer not found")
    return map_customer_summary(_tuple_to_summary_row(row))


def _tuple_to_dashboard_row(
    t: tuple[Customer, CustomerEligibility | None, CustomerProfile | None],
) -> CustomerDashboardRow:
    c, e, p = t
    return CustomerDashboardRow(
        entity_ulid=c.entity_ulid,
        status=c.status,
        intake_step=c.intake_step,
        intake_completed_at_iso=c.intake_completed_at_iso,
        needs_state=c.needs_state,
        watchlist=bool(c.watchlist),
        veteran_status=(e.veteran_status if e else "unknown"),
        homeless_status=(e.homeless_status if e else "unknown"),
        assessment_version=(p.assessment_version if p else 0),
        last_assessed_at_iso=(p.last_assessed_at_iso if p else None),
        tier1_min=c.tier1_min,
        tier2_min=c.tier2_min,
        tier3_min=c.tier3_min,
        flag_tier1_immediate=bool(c.flag_tier1_immediate),
    )


def get_customer_dashboard(entity_ulid: str) -> CustomerDashboardView:
    stmt = (
        select(Customer, CustomerEligibility, CustomerProfile)
        .outerjoin(
            CustomerEligibility,
            CustomerEligibility.entity_ulid == Customer.entity_ulid,
        )
        .outerjoin(
            CustomerProfile,
            CustomerProfile.entity_ulid == Customer.entity_ulid,
        )
        .where(Customer.entity_ulid == entity_ulid)
    )

    row = db.session.execute(stmt).first()
    if row is None:
        raise LookupError("customer not found")

    r = _tuple_to_dashboard_row(row)
    return map_customer_dashboard(r)


def get_customer_eligibility(entity_ulid: str) -> CustomerEligibilityView:
    e = db.session.get(CustomerEligibility, entity_ulid)
    if e is None:
        # Either create/ensure facet earlier, or treat as unknown snapshot:
        raise LookupError("customer eligibility missing")

    r = CustomerEligibilityRow(
        entity_ulid=e.entity_ulid,
        veteran_status=e.veteran_status,
        veteran_method=e.veteran_method,
        branch=e.branch,
        era=e.era,
        homeless_status=e.homeless_status,
        approved_by_ulid=e.approved_by_ulid,
        approved_at_iso=e.approved_at_iso,
    )
    return map_customer_eligibility(r)


def get_customer_overview_vm(entity_ulid: str) -> CustomerOverviewVM:
    ent = ensure_entity_ulid(entity_ulid)
    dash = get_customer_dashboard(ent)
    elig = get_customer_eligibility(ent)
    ratings = get_current_needs_ratings(ent)
    display_name = get_entity_display_name(ent)

    # Policy-driven later; for now "due" means never assessed.
    reassess_due = dash.last_assessed_at_iso is None

    return CustomerOverviewVM(
        entity_ulid=ent,
        display_name=display_name,
        dash=dash,
        elig=elig,
        ratings=ratings,
        reassess_due=reassess_due,
    )


# -----------------
# Intake/Update
# Functions
# -----------------


def ensure_customer_facets(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> ChangeSetDTO:
    """
    Ensure facet rows exist:
      - customer_customer
      - customer_eligibility
      - customer_profile

    Service may flush + emit (session-bound). Route commits/rolls back.
    """
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    changed: list[str] = []
    changed_any = False

    c = db.session.get(Customer, ent)

    # if customer exists but is still at ensure, advance to eligibility
    if c is not None and c.intake_step == "ensure":
        _set_intake_step(c, "eligibility", changed)

    if c is None:
        c = Customer(
            entity_ulid=ent,
            status="intake",
            intake_step="eligibility",
            needs_state="not_started",
            watchlist=False,
        )
        db.session.add(c)
        changed_any = True
        changed.extend(
            [
                "customer.status",
                "customer.intake_step",
                "customer.needs_state",
                "customer.watchlist",
            ]
        )

    e = db.session.get(CustomerEligibility, ent)
    if e is None:
        e = CustomerEligibility(entity_ulid=ent)
        db.session.add(e)
        changed_any = True
        changed.append("eligibility.created")

    p = db.session.get(CustomerProfile, ent)
    if p is None:
        p = CustomerProfile(entity_ulid=ent, assessment_version=0)
        db.session.add(p)
        changed_any = True
        changed.append("profile.created")

    noop = not changed_any
    if noop:
        return ChangeSetDTO(
            entity_ulid=ent,
            created=False,
            noop=True,
            changed_fields=(),
            next_step=None,
        )

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="customer_facets_ensured",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs={"step": "ensure"},
        changed={"fields": changed},
        happened_at_utc=now,
    )

    return ChangeSetDTO(
        entity_ulid=ent,
        created=True,
        noop=False,
        changed_fields=tuple(changed),
        next_step="eligibility",
    )


def set_customer_eligibility(
    *,
    entity_ulid: str,
    veteran_status: str,
    homeless_status: str,
    veteran_method: str | None = None,
    branch: str | None = None,
    era: str | None = None,
    actor_ulid: str | None,
    request_id: str,
) -> ChangeSetDTO:
    """
    Update CustomerEligibility (PK=FK facet) with strict invariants + no-op.

    Services behavior:
    - Mutates + flushes only when changes exist.
    - Emits event_bus after flush only when not noop (unit-of-work semantics).
    - Never commits.

    changed_fields canon:
      eligibility.veteran_status
      eligibility.veteran_method
      eligibility.branch
      eligibility.era
      eligibility.homeless_status
      eligibility.approved_by_ulid
      eligibility.approved_at_iso
    """
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()
    v_status = _norm(veteran_status)
    h_status = _norm(homeless_status)
    v_method = _norm(veteran_method)
    v_branch = _norm(branch)
    v_era = _norm(era)

    if v_status not in VETERAN_STATUS:
        raise ValueError(f"invalid veteran_status: {v_status!r}")
    if h_status not in HOMELESS_STATUS:
        raise ValueError(f"invalid homeless_status: {h_status!r}")
    if v_method is not None and v_method not in VETERAN_METHOD:
        raise ValueError(f"invalid veteran_method: {v_method!r}")
    if v_branch is not None and v_branch not in BRANCH:
        raise ValueError(f"invalid branch: {v_branch!r}")
    if v_era is not None and v_era not in ERA:
        raise ValueError(f"invalid era: {v_era!r}")

    # Ensure parent facet exists (wizard should have created it, but be robust).
    cust = db.session.get(Customer, ent)
    if cust is None:
        raise LookupError("customer facet missing")

    changed: list[str] = []
    _set_intake_step(cust, "needs_tier1", changed)

    created = False
    elig = db.session.get(CustomerEligibility, ent)
    if elig is None:
        elig = CustomerEligibility(entity_ulid=ent)  # type: ignore[arg-type]
        db.session.add(elig)
        created = True

    # Snapshot old values for no-op + changed_fields.
    before = {
        "veteran_status": elig.veteran_status,
        "veteran_method": elig.veteran_method,
        "branch": elig.branch,
        "era": elig.era,
        "homeless_status": elig.homeless_status,
        "approved_by_ulid": elig.approved_by_ulid,
        "approved_at_iso": elig.approved_at_iso,
    }

    # Apply normalization + invariants (mirror DB constraints).
    # - If veteran_status != verified: clear method + approvals.
    # - If verified: method required.
    # - If method == other: approver required (+ timestamp).
    elig.veteran_status = v_status  # type: ignore[assignment]
    elig.homeless_status = h_status  # type: ignore[assignment]

    # Branch/Era are “customer artifacts”; keep them if provided,
    # but clear if explicitly not a veteran.
    if v_status == "not_veteran":
        elig.branch = None
        elig.era = None
    else:
        elig.branch = v_branch  # type: ignore[assignment]
        elig.era = v_era  # type: ignore[assignment]

    if v_status != "verified":
        elig.veteran_method = None
        elig.approved_by_ulid = None
        elig.approved_at_iso = None
    else:
        if v_method is None:
            raise ValueError(
                "veteran_method is required when veteran_status='verified'"
            )
        elig.veteran_method = v_method  # type: ignore[assignment]

        if v_method == "other":
            if not actor_ulid:
                raise ValueError(
                    "actor_ulid is required to approve method='other'"
                )
            # Only update approval timestamp when approval is being established
            # (prevents spurious “touch” updates on resubmits).
            needs_approval_ts = (
                before["veteran_method"] != "other"
                or before["approved_by_ulid"] != actor_ulid
                or before["approved_at_iso"] is None
            )
            elig.approved_by_ulid = actor_ulid
            if needs_approval_ts:
                elig.approved_at_iso = now
        else:
            elig.approved_by_ulid = None
            elig.approved_at_iso = None

    # Compute changed_fields canon names.
    after = {
        "veteran_status": elig.veteran_status,
        "veteran_method": elig.veteran_method,
        "branch": elig.branch,
        "era": elig.era,
        "homeless_status": elig.homeless_status,
        "approved_by_ulid": elig.approved_by_ulid,
        "approved_at_iso": elig.approved_at_iso,
    }

    elig_changed: list[str] = []
    for k in after:
        if before[k] != after[k]:
            elig_changed.append(f"eligibility.{k}")

    changed.extend(elig_changed)

    noop = (not created) and (len(changed) == 0)
    if noop:
        return ChangeSetDTO(
            entity_ulid=ent,
            created=False,
            noop=True,
            changed_fields=(),
            next_step=None,
        )

    db.session.flush()

    # Session-bound emit: safe because it will only “publish” on commit.
    event_bus.emit(
        domain="customers",
        operation="customer_eligibility_updated",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        happened_at_utc=now,
        refs={"step": "eligibility"},
        changed={"fields": changed},
    )

    return ChangeSetDTO(
        entity_ulid=ent,
        created=created,
        noop=False,
        changed_fields=tuple(changed),
        next_step="needs_tier1",
    )


def needs_begin(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> ChangeSetDTO:
    """
    Begin a needs assessment.
    - assessment_version += 1
    - needs_state -> in_progress
    - create 12 CustomerProfileRating rows as 'na' for the new version
    """
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()
    changed: list[str] = []

    # Ensure facets exist (or call your ensure_customer_facets here)
    c = db.session.get(Customer, ent)
    if c is None:
        raise LookupError(
            "customer facet missing"
        )  # wizard should ensure first

    p = db.session.get(CustomerProfile, ent)
    if p is None:
        p = CustomerProfile(entity_ulid=ent, assessment_version=0)
        db.session.add(p)
        changed.append("profile.created")

    # If already in progress, treat as noop (or raise if you want stricter UX)
    if c.needs_state == "in_progress":
        return ChangeSetDTO(ent, False, True, (), None)

    # Start new version
    p.assessment_version += 1
    c.needs_state = "in_progress"
    _set_intake_step(c, "needs_tier1", changed)

    changed.extend(
        [
            "profile.assessment_version",
            "customer.needs_state",
        ]
    )

    # Precreate 12 rows for this version
    v = p.assessment_version
    rows: list[CustomerProfileRating] = []
    for k in NEEDS_CATEGORY_KEY:
        rows.append(
            CustomerProfileRating(
                entity_ulid=ent,
                assessment_version=v,
                category_key=k,
                rating_value="na",
            )
        )
    db.session.add_all(rows)
    changed.append("profile_rating.created_12")

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="customer_needs_begun",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs={"step": "needs_begin", "assessment_version": v},
        changed={"fields": changed},
        happened_at_utc=now,
    )

    return ChangeSetDTO(
        entity_ulid=ent,
        created=True,
        noop=False,
        changed_fields=tuple(changed),
        next_step="needs_tier1",
    )


def needs_set_block(
    *,
    entity_ulid: str,
    ratings: dict[str, str],  # {category_key: rating_value}
    request_id: str,
    actor_ulid: str | None,
    next_step: str | None = None,
) -> ChangeSetDTO:
    """
    Update one or more category ratings for the CURRENT assessment_version,
    and recompute cached cues on Customer.

    ratings values must be in: immediate|marginal|sufficient|unknown|na
    """
    # variable assignments
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    # Validate + normalize input keys/values once (pre-flush).
    norm_ratings: dict[str, str] = {}
    for k, v in (ratings or {}).items():
        kk = str(k or "").strip().lower()
        vv = str(v or "").strip().lower()
        if kk not in NEEDS_CATEGORY_KEY:
            raise ValueError(f"invalid category_key: {k!r}")
        if vv not in RATING_ALLOWED:
            raise ValueError(f"invalid rating_value for {kk!r}: {v!r}")
        norm_ratings[kk] = vv

    c = db.session.get(Customer, ent)
    if c is None:
        raise LookupError("customer not found")
    p = db.session.get(CustomerProfile, ent)
    if p is None or p.assessment_version < 1:
        raise ValueError(
            "needs assessment not started (call needs_begin first)"
        )

    # Had to move this down from variable assignments to pick up "p"
    v = p.assessment_version
    REFS = {"step": "needs_set_block", "assessment_version": v}

    if c.needs_state != "in_progress":
        raise ValueError("needs_state is not in_progress")

    v = p.assessment_version
    changed: list[str] = []

    # Load existing rows for this version
    stmt = (
        select(CustomerProfileRating)
        .where(CustomerProfileRating.entity_ulid == ent)
        .where(CustomerProfileRating.assessment_version == v)
    )
    existing = db.session.execute(stmt).scalars().all()
    by_key = {r.category_key: r for r in existing}

    # Ensure the 12 rows exist (defensive; begin should have created them)
    if len(by_key) != len(NEEDS_CATEGORY_KEY):
        raise RuntimeError("needs rows missing; expected 12 rating rows")

    # Apply updates

    for k, new_val in norm_ratings.items():
        r = by_key[k]
        if r.rating_value != new_val:
            r.rating_value = new_val
            changed.append(f"profile_rating.{k}")

    # No rating changes? maybe still advance step.
    if not changed:
        if next_step in ("needs_tier2", "needs_tier3", "review"):
            _set_intake_step(c, next_step, changed)

        # If still no changes, it's a true noop.
        if not changed:
            return ChangeSetDTO(ent, False, True, (), next_step)

        # Step changed only: flush + emit + return (no rollup recompute needed)
        db.session.flush()
        event_bus.emit(
            domain="customers",
            operation="customer_needs_updated",
            request_id=rid,
            actor_ulid=act,
            target_ulid=ent,
            refs=REFS,
            changed={"fields": changed},
            happened_at_utc=now,
        )
        return ChangeSetDTO(
            entity_ulid=ent,
            created=False,
            noop=False,
            changed_fields=tuple(changed),
            next_step=next_step,
        )

    # Recompute rollups from current version rows
    rating_values = {k: by_key[k].rating_value for k in NEEDS_CATEGORY_KEY}
    t1 = _tier_min_for(rating_values, TIER1)
    t2 = _tier_min_for(rating_values, TIER2)
    t3 = _tier_min_for(rating_values, TIER3)

    if c.tier1_min != t1:
        c.tier1_min = t1
        changed.append("customer.tier1_min")
    if c.tier2_min != t2:
        c.tier2_min = t2
        changed.append("customer.tier2_min")
    if c.tier3_min != t3:
        c.tier3_min = t3
        changed.append("customer.tier3_min")

    # "raw" flag (watchlist does NOT rewrite this; compute effective elsewhere)
    new_flag = t1 == 1
    if bool(c.flag_tier1_immediate) != new_flag:
        c.flag_tier1_immediate = new_flag
        changed.append("customer.flag_tier1_immediate")
    # advance wizard step if caller provided one
    if next_step in ("needs_tier2", "needs_tier3", "review"):
        _set_intake_step(c, next_step, changed)

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="customer_needs_updated",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs=REFS,
        changed={"fields": changed},
        happened_at_utc=now,
    )

    return ChangeSetDTO(
        entity_ulid=ent,
        created=False,
        noop=False,
        changed_fields=tuple(changed),
        next_step=next_step,
    )


def needs_skip(
    *, entity_ulid: str, request_id: str, actor_ulid: str | None
) -> ChangeSetDTO:
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()
    c = db.session.get(Customer, ent)
    if c is None:
        raise LookupError("customer not found")
    if c.needs_state == "skipped":
        return ChangeSetDTO(ent, False, True, (), None)

    c.needs_state = "skipped"
    _set_intake_step(c, "review", changed := ["customer.needs_state"])

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="customer_needs_skipped",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs={"step": "needs_skip"},
        changed={"fields": changed},
        happened_at_utc=now,
    )
    return ChangeSetDTO(ent, False, False, tuple(changed), "review")


def needs_complete(
    *, entity_ulid: str, request_id: str, actor_ulid: str | None
) -> ChangeSetDTO:
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()
    c = db.session.get(Customer, ent)
    p = db.session.get(CustomerProfile, ent)
    if c is None or p is None:
        raise LookupError("customer/profile missing")
    if c.needs_state == "complete":
        return ChangeSetDTO(ent, False, True, (), None)

    changed: list[str] = []

    c.needs_state = "complete"
    changed.append("customer.needs_state")

    _set_intake_step(c, "complete", changed)

    if c.intake_completed_at_iso != now:
        c.intake_completed_at_iso = now
        changed.append("customer.intake_completed_at_iso")

    # optional: promote from intake → active
    if c.status != "active":
        c.status = "active"
        changed.append("customer.status")

    p.last_assessed_at_iso = now
    changed.append("profile.last_assessed_at_iso")

    if p.last_assessed_by_ulid != act:
        p.last_assessed_by_ulid = act
        changed.append("profile.last_assessed_by_ulid")

    db.session.flush()

    event_bus.emit(
        domain="customers",
        operation="customer_needs_completed",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs={
            "step": "needs_complete",
            "assessment_version": p.assessment_version,
        },
        changed={"fields": changed},
        happened_at_utc=now,
    )
    return ChangeSetDTO(ent, False, False, tuple(changed), "review")


# -----------------
# History Blob
# Handling Commands
# -----------------


def tags_to_csv(tags: tuple[str, ...]) -> str | None:
    uniq = sorted({t for t in tags if t})
    return ",".join(uniq) if uniq else None


def csv_to_tags(csv: str | None) -> tuple[str, ...]:
    if not csv:
        return ()
    parts = [p.strip() for p in csv.split(",")]
    parts = [p for p in parts if p]
    return tuple(parts)


@lru_cache(maxsize=1)
def _history_blob_validator() -> Draft202012Validator:
    here = Path(__file__).resolve().parent
    schema_path = (
        here / "data" / "schemas" / "customer_history_blob.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _parse_history_blob(
    blob: str | Mapping[str, Any]
) -> tuple[str, ParsedHistoryBlobDTO]:
    if isinstance(blob, str):
        raw = json.loads(blob)
        blob_json = stable_dumps(raw)
    else:
        raw = dict(blob)
        blob_json = stable_dumps(raw)

    if not isinstance(raw, dict):
        raise ValueError("history blob must be a JSON object")

    env = raw.get("envelope")
    payload = raw.get("payload")

    if not isinstance(env, dict):
        raise ValueError("history blob missing envelope object")
    if not isinstance(payload, dict):
        raise ValueError("history blob missing payload object")

    # Validate envelope+payload shape, but we only *interpret* envelope.
    _history_blob_validator().validate(raw)

    public_tags = tuple(env.get("public_tags") or ())
    admin_tags = tuple(env.get("admin_tags") or ())

    dto = ParsedHistoryBlobDTO(
        envelope=EnvelopeDTO(
            schema_name=env["schema_name"],
            schema_version=int(env["schema_version"]),
            title=env["title"],
            summary=env["summary"],
            severity=env["severity"],
            happened_at_iso=env["happened_at"],
            source_slice=env["source_slice"],
            source_ref_ulid=env.get("source_ref_ulid"),
            created_by_actor_ulid=env.get("created_by_actor_ulid"),
            public_tags=public_tags,
            admin_tags=admin_tags,
            dedupe_key=env.get("dedupe_key"),
            refs=env.get("refs"),
        ),
        payload=payload,
    )
    return blob_json, dto


def append_history_entry(
    *,
    target_entity_ulid: str,
    kind: str,
    blob_json: str | Mapping[str, Any],
    actor_ulid: str,
    request_id: str,
) -> str:
    ent = ensure_entity_ulid(target_entity_ulid)
    act = ensure_actor_ulid(actor_ulid)
    ensure_request_id(request_id)

    if not kind or not kind.strip():
        raise ValueError("kind is required")

    # request_id is accepted for correlation;
    # Customers doesn't emit ledger here.
    cust = db.session.get(Customer, ent)
    if cust is None:
        raise LookupError("customer facet missing")

    blob_str, parsed = _parse_history_blob(blob_json)
    env = parsed.envelope

    row = CustomerHistory(
        entity_ulid=ent,
        kind=kind,
        happened_at_iso=env.happened_at_iso,
        source_slice=env.source_slice,
        source_ref_ulid=env.source_ref_ulid,
        schema_name=env.schema_name,
        schema_version=env.schema_version,
        title=env.title,
        summary=env.summary,
        severity=env.severity,
        public_tags_csv=tags_to_csv(env.public_tags),
        has_admin_tags=bool(env.admin_tags),
        admin_tags_csv=tags_to_csv(env.admin_tags),
        created_by_actor_ulid=env.created_by_actor_ulid or act,
        data_json=blob_str,
    )

    db.session.add(row)
    db.session.flush()
    return row.ulid


def _strip_admin_tags(dto: ParsedHistoryBlobDTO) -> ParsedHistoryBlobDTO:
    env = dto.envelope
    env2 = EnvelopeDTO(
        schema_name=env.schema_name,
        schema_version=env.schema_version,
        title=env.title,
        summary=env.summary,
        severity=env.severity,
        happened_at_iso=env.happened_at_iso,
        source_slice=env.source_slice,
        source_ref_ulid=env.source_ref_ulid,
        created_by_actor_ulid=env.created_by_actor_ulid,
        public_tags=env.public_tags,
        admin_tags=(),
        dedupe_key=env.dedupe_key,
        refs=env.refs,
    )
    return ParsedHistoryBlobDTO(envelope=env2, payload=dto.payload)


def list_customer_history_items(
    *, entity_ulid: str, page: int, per_page: int
) -> Page[CustomerHistoryItemView]:
    ent = ensure_entity_ulid(entity_ulid)
    stmt = (
        select(CustomerHistory)
        .where(CustomerHistory.entity_ulid == ent)
        .order_by(CustomerHistory.happened_at_iso.desc())
    )

    def _to_row(h: CustomerHistory) -> CustomerHistoryItemRow:
        return CustomerHistoryItemRow(
            ulid=h.ulid,
            entity_ulid=h.entity_ulid,
            kind=h.kind,
            happened_at_iso=h.happened_at_iso,
            severity=h.severity,
            title=h.title,
            summary=h.summary,
            source_slice=h.source_slice,
            source_ref_ulid=h.source_ref_ulid,
            public_tags=csv_to_tags(h.public_tags_csv),
        )

    return (
        paginate(stmt, page=page, per_page=per_page)
        .map(_to_row)
        .map(map_customer_history_item)
    )


def get_customer_history_detail_public(
    *, entity_ulid: str, history_ulid: str
) -> CustomerHistoryDetailView:
    ent = ensure_entity_ulid(entity_ulid)
    h = db.session.get(CustomerHistory, history_ulid)
    if h is None or h.entity_ulid != ent:
        raise LookupError("history entry not found")

    _blob_str, parsed = _parse_history_blob(h.data_json)
    parsed2 = _strip_admin_tags(parsed)

    row = CustomerHistoryDetailRow(
        ulid=h.ulid,
        entity_ulid=h.entity_ulid,
        kind=h.kind,
        happened_at_iso=h.happened_at_iso,
        parsed=parsed2,
    )
    return map_customer_history_detail(row)


def list_admin_inbox_items(
    *, page: int, per_page: int
) -> Page[AdminInboxItemView]:
    stmt = (
        select(CustomerHistory, Customer)
        .join(Customer, Customer.entity_ulid == CustomerHistory.entity_ulid)
        .where(CustomerHistory.has_admin_tags == True)  # noqa: E712
        .order_by(CustomerHistory.happened_at_iso.desc())
    )

    def _to_row(t: tuple[CustomerHistory, Customer]) -> AdminInboxItemRow:
        h, c = t
        return AdminInboxItemRow(
            history_ulid=h.ulid,
            entity_ulid=h.entity_ulid,
            customer_status=c.status,
            watchlist=bool(c.watchlist),
            tier1_min=c.tier1_min,
            flag_tier1_immediate=bool(c.flag_tier1_immediate),
            happened_at_iso=h.happened_at_iso,
            severity=h.severity,
            title=h.title,
            summary=h.summary,
            admin_tags=csv_to_tags(h.admin_tags_csv),
        )

    return (
        paginate(stmt, page=page, per_page=per_page)
        .map(_to_row)
        .map(map_admin_inbox_item)
    )
