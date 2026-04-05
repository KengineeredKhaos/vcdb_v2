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
from app.lib.ids import new_ulid
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
    CustomerProviderMatchItemRow,
    CustomerProviderMatchItemView,
    CustomerProviderMatchRow,
    CustomerProviderMatchView,
    CustomerProviderNeedOptionRow,
    CustomerProviderNeedOptionView,
    CustomerSummaryRow,
    CustomerSummaryView,
    EnvelopeDTO,
    ParsedHistoryBlobDTO,
    ReferralComposeView,
    ReferralOutcomeComposeView,
    map_admin_inbox_item,
    map_customer_dashboard,
    map_customer_eligibility,
    map_customer_history_detail,
    map_customer_history_item,
    map_customer_provider_match,
    map_customer_provider_match_item,
    map_customer_provider_need_option,
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
    HOUSING_STATUS,
    INTAKE_STEPS,
    NEED_LABELS,
    NEEDS_CATEGORY_KEY,
    RANK,
    RATING_ALLOWED,
    REFERRAL_MATCH_BUCKETS,
    REFERRAL_METHODS,
    REFERRAL_OUTCOMES,
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


def _require_len(
    field: str,
    value: str | None,
    *,
    max_len: int,
    required: bool = False,
) -> str | None:
    v = _norm(value)
    if not v:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if len(v) > max_len:
        raise ValueError(f"{field} exceeds {max_len} characters")
    return v


def _need_label(need_key: str) -> str:
    return NEED_LABELS.get(
        need_key, str(need_key or "").replace("_", " ").title()
    )


def _outcome_label(outcome: str) -> str:
    return str(outcome or "").replace("_", " ").title()


def _tier_min_for(
    ratings_by_key: dict[str, str | None],
    keys: tuple[str, ...],
) -> int | None:
    ranks: list[int] = []
    for k in keys:
        v = ratings_by_key.get(k)
        if not v:
            continue
        r = RANK.get(v)
        if r is not None:
            ranks.append(r)
    return min(ranks) if ranks else None


def _set_changed(
    obj: object,
    attr: str,
    value: Any,
    field: str,
    changed: list[str],
) -> None:
    if getattr(obj, attr) != value:
        setattr(obj, attr, value)
        changed.append(field)


def _is_tier_assessed(
    by_key: dict[str, CustomerProfileRating],
    keys: tuple[str, ...],
) -> bool:
    return all(bool(by_key.get(k) and by_key[k].is_assessed) for k in keys)


def _compute_eligibility_complete(elig: CustomerEligibility | None) -> bool:
    if elig is None:
        return False

    if elig.veteran_status not in ("verified", "unverified", "not_veteran"):
        return False
    if elig.housing_status not in ("housed", "unhoused"):
        return False

    if elig.veteran_status == "verified":
        if not elig.veteran_method:
            return False
        if elig.veteran_method == "other":
            return bool(elig.approved_by_ulid and elig.approved_at_iso)

    return True


def _recompute_customer_cues(
    *,
    customer: Customer,
    eligibility: CustomerEligibility | None,
    ratings: list[CustomerProfileRating],
    changed: list[str],
) -> None:
    by_key = {r.category_key: r for r in ratings}
    rating_values = {
        k: r.rating_value
        for k, r in by_key.items()
        if r.is_assessed and r.rating_value
    }

    eligibility_complete = _compute_eligibility_complete(eligibility)
    tier1_assessed = _is_tier_assessed(by_key, TIER1)
    tier2_assessed = _is_tier_assessed(by_key, TIER2)
    tier3_assessed = _is_tier_assessed(by_key, TIER3)

    tier1_unlocked = eligibility_complete and tier1_assessed
    tier2_unlocked = eligibility_complete and tier2_assessed
    tier3_unlocked = eligibility_complete and tier3_assessed
    assessment_complete = tier1_assessed and tier2_assessed and tier3_assessed

    t1 = _tier_min_for(rating_values, TIER1)
    t2 = _tier_min_for(rating_values, TIER2)
    t3 = _tier_min_for(rating_values, TIER3)

    _set_changed(
        customer,
        "eligibility_complete",
        eligibility_complete,
        "customer.eligibility_complete",
        changed,
    )
    _set_changed(
        customer,
        "tier1_assessed",
        tier1_assessed,
        "customer.tier1_assessed",
        changed,
    )
    _set_changed(
        customer,
        "tier2_assessed",
        tier2_assessed,
        "customer.tier2_assessed",
        changed,
    )
    _set_changed(
        customer,
        "tier3_assessed",
        tier3_assessed,
        "customer.tier3_assessed",
        changed,
    )
    _set_changed(
        customer,
        "tier1_unlocked",
        tier1_unlocked,
        "customer.tier1_unlocked",
        changed,
    )
    _set_changed(
        customer,
        "tier2_unlocked",
        tier2_unlocked,
        "customer.tier2_unlocked",
        changed,
    )
    _set_changed(
        customer,
        "tier3_unlocked",
        tier3_unlocked,
        "customer.tier3_unlocked",
        changed,
    )
    _set_changed(
        customer,
        "assessment_complete",
        assessment_complete,
        "customer.assessment_complete",
        changed,
    )
    _set_changed(customer, "tier1_min", t1, "customer.tier1_min", changed)
    _set_changed(customer, "tier2_min", t2, "customer.tier2_min", changed)
    _set_changed(customer, "tier3_min", t3, "customer.tier3_min", changed)
    _set_changed(
        customer,
        "flag_tier1_immediate",
        t1 == 1,
        "customer.flag_tier1_immediate",
        changed,
    )

    if (
        customer.status == "intake"
        and eligibility_complete
        and tier1_unlocked
    ):
        customer.status = "active"
        changed.append("customer.status")


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
        select(CustomerProfileRating)
        .where(CustomerProfileRating.entity_ulid == ent)
        .where(
            CustomerProfileRating.assessment_version == p.assessment_version
        )
    )
    rows = db.session.execute(stmt).scalars().all()
    out: dict[str, str] = {}
    for row in rows:
        if row.is_assessed and row.rating_value:
            out[row.category_key] = row.rating_value
    return out


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


def _need_tier(need_key: str) -> int:
    if need_key in TIER1:
        return 1
    if need_key in TIER2:
        return 2
    if need_key in TIER3:
        return 3
    raise ValueError(f"invalid need_key: {need_key!r}")


def list_provider_need_options() -> (
    tuple[CustomerProviderNeedOptionView, ...]
):
    out: list[CustomerProviderNeedOptionView] = []
    for key in NEEDS_CATEGORY_KEY:
        out.append(
            map_customer_provider_need_option(
                CustomerProviderNeedOptionRow(
                    key=key,
                    label=_need_label(key),
                    tier=_need_tier(key),
                )
            )
        )
    return tuple(out)


def _provider_match_item_from_dto(
    item: Mapping[str, Any],
    *,
    labels: Mapping[str, str],
) -> CustomerProviderMatchItemView:
    entity_ulid = str(item.get("entity_ulid") or "")
    return map_customer_provider_match_item(
        CustomerProviderMatchItemRow(
            entity_ulid=entity_ulid,
            display_name=labels.get(entity_ulid, entity_ulid),
            readiness_status=str(item.get("readiness_status") or ""),
            mou_status=str(item.get("mou_status") or ""),
            matched_capability_keys=tuple(
                str(v) for v in (item.get("matched_capability_keys") or [])
            ),
            bucket=str(item.get("bucket") or ""),
            reason_codes=tuple(
                str(v) for v in (item.get("reason_codes") or [])
            ),
        )
    )


def get_provider_match_vm(
    *,
    entity_ulid: str,
    need_key: str | None,
    include_adjacent: bool = True,
) -> CustomerProviderMatchView:
    ent = ensure_entity_ulid(entity_ulid)
    dash = get_customer_dashboard(ent)
    display_name = get_entity_display_name(ent)
    need_options = list_provider_need_options()
    selected = str(need_key or "").strip().lower() or None
    ratings = get_current_needs_ratings(ent)

    if selected is None:
        return map_customer_provider_match(
            CustomerProviderMatchRow(
                entity_ulid=ent,
                display_name=display_name,
                dash=dash,
                need_options=need_options,
                need_key=None,
                need_label=None,
                need_tier=None,
                need_rating=None,
                tier_priority=None,
                customer_gate=None,
                blocked_reason=None,
                operator_cautions=(),
                exact_matches=(),
                adjacent_matches=(),
                review_matches=(),
                as_of_iso=None,
            )
        )

    if selected not in NEEDS_CATEGORY_KEY:
        raise ValueError(f"invalid need_key: {need_key!r}")

    from app.extensions.contracts import resources_v2

    result = resources_v2.match_customer_need(
        customer_ulid=ent,
        need_key=selected,
        include_adjacent=bool(include_adjacent),
    )

    resource_ulids: list[str] = []
    for bucket_key in (
        "exact_matches",
        "adjacent_matches",
        "review_matches",
    ):
        for item in result.get(bucket_key, []) or []:
            resource_ulid = str(item.get("entity_ulid") or "")
            if resource_ulid:
                resource_ulids.append(resource_ulid)

    labels = get_entity_display_names(resource_ulids)
    exact = tuple(
        _provider_match_item_from_dto(item, labels=labels)
        for item in (result.get("exact_matches") or [])
    )
    adjacent = tuple(
        _provider_match_item_from_dto(item, labels=labels)
        for item in (result.get("adjacent_matches") or [])
    )
    review = tuple(
        _provider_match_item_from_dto(item, labels=labels)
        for item in (result.get("review_matches") or [])
    )

    return map_customer_provider_match(
        CustomerProviderMatchRow(
            entity_ulid=ent,
            display_name=display_name,
            dash=dash,
            need_options=need_options,
            need_key=selected,
            need_label=_need_label(selected),
            need_tier=_need_tier(selected),
            need_rating=ratings.get(selected),
            tier_priority=result.get("tier_priority"),
            customer_gate=result.get("customer_gate"),
            blocked_reason=result.get("blocked_reason"),
            operator_cautions=tuple(
                str(v) for v in (result.get("operator_cautions") or [])
            ),
            exact_matches=exact,
            adjacent_matches=adjacent,
            review_matches=review,
            as_of_iso=result.get("as_of_iso"),
        )
    )


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
        eligibility_complete=bool(c.eligibility_complete),
        entity_package_incomplete=bool(c.entity_package_incomplete),
        tier1_assessed=bool(c.tier1_assessed),
        tier2_assessed=bool(c.tier2_assessed),
        tier3_assessed=bool(c.tier3_assessed),
        tier1_unlocked=bool(c.tier1_unlocked),
        tier2_unlocked=bool(c.tier2_unlocked),
        tier3_unlocked=bool(c.tier3_unlocked),
        assessment_complete=bool(c.assessment_complete),
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
        watchlist=bool(c.watchlist),
        eligibility_complete=bool(c.eligibility_complete),
        entity_package_incomplete=bool(c.entity_package_incomplete),
        veteran_status=(e.veteran_status if e else "unknown"),
        housing_status=(e.housing_status if e else "unknown"),
        assessment_version=(p.assessment_version if p else 0),
        last_assessed_at_iso=(p.last_assessed_at_iso if p else None),
        tier1_assessed=bool(c.tier1_assessed),
        tier2_assessed=bool(c.tier2_assessed),
        tier3_assessed=bool(c.tier3_assessed),
        tier1_unlocked=bool(c.tier1_unlocked),
        tier2_unlocked=bool(c.tier2_unlocked),
        tier3_unlocked=bool(c.tier3_unlocked),
        assessment_complete=bool(c.assessment_complete),
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
        r = CustomerEligibilityRow(
            entity_ulid=entity_ulid,
            veteran_status="unknown",
            veteran_method=None,
            branch=None,
            era=None,
            housing_status="unknown",
            approved_by_ulid=None,
            approved_at_iso=None,
        )
        return map_customer_eligibility(r)

    r = CustomerEligibilityRow(
        entity_ulid=e.entity_ulid,
        veteran_status=e.veteran_status,
        veteran_method=e.veteran_method,
        branch=e.branch,
        era=e.era,
        housing_status=e.housing_status,
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
    created_any = False

    c = db.session.get(Customer, ent)

    if c is not None and c.intake_step == "ensure":
        _set_intake_step(c, "eligibility", changed)
        if changed:
            changed_any = True

    if c is None:
        c = Customer(
            entity_ulid=ent,
            status="intake",
            intake_step="eligibility",
            watchlist=False,
        )
        db.session.add(c)
        changed_any = True
        created_any = True
        changed.extend(
            [
                "customer.status",
                "customer.intake_step",
                "customer.watchlist",
            ]
        )

    e = db.session.get(CustomerEligibility, ent)
    if e is None:
        e = CustomerEligibility(entity_ulid=ent)
        db.session.add(e)
        changed_any = True
        created_any = True
        changed.append("eligibility.created")

    p = db.session.get(CustomerProfile, ent)
    if p is None:
        p = CustomerProfile(entity_ulid=ent, assessment_version=0)
        db.session.add(p)
        changed_any = True
        created_any = True
        changed.append("profile.created")

    if not changed_any:
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
        created=created_any,
        noop=False,
        changed_fields=tuple(changed),
        next_step="eligibility",
    )


def set_customer_eligibility(
    *,
    entity_ulid: str,
    veteran_status: str,
    housing_status: str,
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
      eligibility.housing_status
      eligibility.approved_by_ulid
      eligibility.approved_at_iso
    """
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()
    v_status = _norm(veteran_status)
    h_status = _norm(housing_status)
    v_method = _norm(veteran_method)
    v_branch = _norm(branch)
    v_era = _norm(era)

    if v_status not in VETERAN_STATUS:
        raise ValueError(f"invalid veteran_status: {v_status!r}")
    if h_status not in HOUSING_STATUS:
        raise ValueError(f"invalid housing_status: {h_status!r}")
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

    rows_stmt = (
        (
            select(CustomerProfileRating)
            .where(CustomerProfileRating.entity_ulid == ent)
            .where(
                CustomerProfileRating.assessment_version
                == cust.profile.assessment_version
            )
        )
        if cust.profile and cust.profile.assessment_version >= 1
        else None
    )
    rows = (
        db.session.execute(rows_stmt).scalars().all()
        if rows_stmt is not None
        else []
    )

    # Snapshot old values for no-op + changed_fields.
    before = {
        "veteran_status": elig.veteran_status,
        "veteran_method": elig.veteran_method,
        "branch": elig.branch,
        "era": elig.era,
        "housing_status": elig.housing_status,
        "approved_by_ulid": elig.approved_by_ulid,
        "approved_at_iso": elig.approved_at_iso,
    }

    # Apply normalization + invariants (mirror DB constraints).
    # - If veteran_status != verified: clear method + approvals.
    # - If verified: method required.
    # - If method == other: approver required (+ timestamp).
    elig.veteran_status = v_status  # type: ignore[assignment]
    elig.housing_status = h_status  # type: ignore[assignment]

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
        "housing_status": elig.housing_status,
        "approved_by_ulid": elig.approved_by_ulid,
        "approved_at_iso": elig.approved_at_iso,
    }

    elig_changed: list[str] = []
    for k in after:
        if before[k] != after[k]:
            elig_changed.append(f"eligibility.{k}")

    changed.extend(elig_changed)
    _recompute_customer_cues(
        customer=cust,
        eligibility=elig,
        ratings=rows,
        changed=changed,
    )

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
    Begin a needs assessment or reassessment.
    - assessment_version += 1 when no current in-progress session exists
    - create 12 CustomerProfileRating rows for the new version with
      is_assessed=False and rating_value unset
    """
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()
    changed: list[str] = []

    c = db.session.get(Customer, ent)
    if c is None:
        raise LookupError("customer facet missing")

    p = db.session.get(CustomerProfile, ent)
    if p is None:
        p = CustomerProfile(entity_ulid=ent, assessment_version=0)
        db.session.add(p)
        changed.append("profile.created")

    if p.assessment_version >= 1 and not c.assessment_complete:
        return ChangeSetDTO(ent, False, True, (), None)

    p.assessment_version += 1
    _set_intake_step(c, "needs_tier1", changed)
    changed.append("profile.assessment_version")

    v = p.assessment_version
    rows: list[CustomerProfileRating] = []
    for k in NEEDS_CATEGORY_KEY:
        rows.append(
            CustomerProfileRating(
                entity_ulid=ent,
                assessment_version=v,
                category_key=k,
                is_assessed=False,
                rating_value=None,
            )
        )
    db.session.add_all(rows)
    changed.append("profile_rating.created_12")

    _recompute_customer_cues(
        customer=c,
        eligibility=db.session.get(CustomerEligibility, ent),
        ratings=rows,
        changed=changed,
    )

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

    ratings values must be in:
    immediate|marginal|sufficient|unknown|not_applicable
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

    v = p.assessment_version
    REFS = {"step": "needs_set_block", "assessment_version": v}
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
        if (not r.is_assessed) or (r.rating_value != new_val):
            r.is_assessed = True
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

    _recompute_customer_cues(
        customer=c,
        eligibility=db.session.get(CustomerEligibility, ent),
        ratings=existing,
        changed=changed,
    )
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

    elig = db.session.get(CustomerEligibility, ent)
    if elig is None:
        raise LookupError("customer eligibility missing")

    rows_stmt = (
        select(CustomerProfileRating)
        .where(CustomerProfileRating.entity_ulid == ent)
        .where(
            CustomerProfileRating.assessment_version == p.assessment_version
        )
        .order_by(CustomerProfileRating.category_key.asc())
    )
    rows = db.session.execute(rows_stmt).scalars().all()

    if c.intake_step == "complete":
        return ChangeSetDTO(ent, False, True, (), None)
    if not c.assessment_complete:
        raise ValueError("assessment not complete")

    changed: list[str] = []

    _set_intake_step(c, "complete", changed)

    if c.intake_completed_at_iso is None:
        c.intake_completed_at_iso = now
        changed.append("customer.intake_completed_at_iso")

    if c.status == "intake" and c.eligibility_complete and c.tier1_unlocked:
        c.status = "active"
        changed.append("customer.status")

    if p.last_assessed_at_iso != now:
        p.last_assessed_at_iso = now
        changed.append("profile.last_assessed_at_iso")

    if p.last_assessed_by_ulid != act:
        p.last_assessed_by_ulid = act
        changed.append("profile.last_assessed_by_ulid")

    db.session.flush()

    history_kind, history_blob = _build_assessment_history_entry(
        entity_ulid=ent,
        actor_ulid=act,
        happened_at=now,
        assessment_version=p.assessment_version,
        eligibility=elig,
        rows=rows,
    )

    history_ulid = append_history_entry(
        target_entity_ulid=ent,
        kind=history_kind,
        blob_json=history_blob,
        actor_ulid=act,
        request_id=rid,
    )

    event_bus.emit(
        domain="customers",
        operation="customer_needs_completed",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs={
            "step": "needs_complete",
            "assessment_version": p.assessment_version,
            "history_ulid": history_ulid,
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


@lru_cache(maxsize=None)
def _json_schema_validator(filename: str) -> Draft202012Validator:
    here = Path(__file__).resolve().parent
    schema_path = here / "data" / "schemas" / filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@lru_cache(maxsize=1)
def _history_blob_validator() -> Draft202012Validator:
    return _json_schema_validator("customer_history_blob.schema.json")


def _referral_payload_validator() -> Draft202012Validator:
    return _json_schema_validator("customer_referral_payload.schema.json")


def _referral_outcome_payload_validator() -> Draft202012Validator:
    return _json_schema_validator(
        "customer_referral_outcome_payload.schema.json"
    )


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


def _assessment_session_type(assessment_version: int) -> str:
    return "initial" if int(assessment_version or 0) <= 1 else "reassessment"


def _tiers_touched_from_rows(
    rows: list[CustomerProfileRating],
) -> list[str]:
    touched: list[str] = []
    by_key = {r.category_key: r for r in rows}

    if all(bool(by_key.get(k) and by_key[k].is_assessed) for k in TIER1):
        touched.append("tier1")
    if all(bool(by_key.get(k) and by_key[k].is_assessed) for k in TIER2):
        touched.append("tier2")
    if all(bool(by_key.get(k) and by_key[k].is_assessed) for k in TIER3):
        touched.append("tier3")

    return touched


def _assessment_factor_list(
    rows: list[CustomerProfileRating],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in sorted(rows, key=lambda x: x.category_key):
        if not r.is_assessed or not r.rating_value:
            continue
        out.append(
            {
                "factor_key": r.category_key,
                "value": r.rating_value,
            }
        )
    return out


def _build_assessment_history_entry(
    *,
    entity_ulid: str,
    actor_ulid: str,
    happened_at: str,
    assessment_version: int,
    eligibility: CustomerEligibility,
    rows: list[CustomerProfileRating],
) -> tuple[str, dict[str, Any]]:
    session_type = _assessment_session_type(assessment_version)

    if session_type == "initial":
        title = "Initial assessment completed"
        summary = (
            "Eligibility resolved and initial customer assessment "
            "recorded."
        )
        kind = "assessment.initial"
    else:
        title = "Annual reassessment completed"
        summary = (
            "Eligibility reviewed and customer reassessment " "recorded."
        )
        kind = "assessment.reassessment"

    blob = {
        "envelope": {
            "schema_name": "customers.assessment.synopsis.v1",
            "schema_version": 1,
            "title": title,
            "summary": summary,
            "severity": "info",
            "happened_at": happened_at,
            "source_slice": "customers",
            "source_ref_ulid": entity_ulid,
            "created_by_actor_ulid": actor_ulid,
            "public_tags": ["assessment"],
            "admin_tags": [],
            "refs": {
                "assessment_version": assessment_version,
                "session_type": session_type,
            },
        },
        "payload": {
            "session_type": session_type,
            "eligibility": {
                "veteran_status": eligibility.veteran_status,
                "veteran_method": eligibility.veteran_method,
                "branch": eligibility.branch,
                "era": eligibility.era,
                "housing_status": eligibility.housing_status,
            },
            "factors": _assessment_factor_list(rows),
            "tiers_touched": _tiers_touched_from_rows(rows),
            "note": None,
        },
    }
    return kind, blob


def _build_referral_history_entry(
    *,
    entity_ulid: str,
    actor_ulid: str,
    happened_at: str,
    referral_ulid: str,
    resource_ulid: str,
    resource_name: str,
    need_key: str,
    match_bucket: str | None,
    method: str,
    synopsis: str,
    note: str | None,
) -> tuple[str, dict[str, Any]]:
    need_label = _need_label(need_key)
    payload = {
        "referral_ulid": referral_ulid,
        "resource_ulid": resource_ulid,
        "resource_name": resource_name,
        "need_key": need_key,
        "need_label": need_label,
        "match_bucket": match_bucket,
        "method": method,
        "note": note,
    }
    _referral_payload_validator().validate(payload)

    return (
        "referral.created",
        {
            "envelope": {
                "schema_name": "customers.referral.synopsis.v1",
                "schema_version": 1,
                "title": "Referral recorded",
                "summary": synopsis,
                "severity": "info",
                "happened_at": happened_at,
                "source_slice": "customers",
                "source_ref_ulid": entity_ulid,
                "created_by_actor_ulid": actor_ulid,
                "public_tags": ["referral"],
                "admin_tags": [],
                "refs": {
                    "referral_ulid": referral_ulid,
                    "resource_ulid": resource_ulid,
                    "need_key": need_key,
                    "method": method,
                    "match_bucket": match_bucket,
                },
            },
            "payload": payload,
        },
    )


def _build_referral_outcome_history_entry(
    *,
    entity_ulid: str,
    actor_ulid: str,
    happened_at: str,
    referral_ulid: str,
    resource_ulid: str,
    resource_name: str,
    need_key: str,
    outcome: str,
    synopsis: str,
    note: str | None,
) -> tuple[str, dict[str, Any]]:
    need_label = _need_label(need_key)
    outcome_label = _outcome_label(outcome)
    payload = {
        "referral_ulid": referral_ulid,
        "resource_ulid": resource_ulid,
        "resource_name": resource_name,
        "need_key": need_key,
        "need_label": need_label,
        "outcome": outcome,
        "outcome_label": outcome_label,
        "note": note,
    }
    _referral_outcome_payload_validator().validate(payload)

    return (
        "referral.outcome_recorded",
        {
            "envelope": {
                "schema_name": "customers.referral_outcome.synopsis.v1",
                "schema_version": 1,
                "title": "Referral outcome recorded",
                "summary": synopsis,
                "severity": "info",
                "happened_at": happened_at,
                "source_slice": "customers",
                "source_ref_ulid": entity_ulid,
                "created_by_actor_ulid": actor_ulid,
                "public_tags": ["referral", "outcome"],
                "admin_tags": [],
                "refs": {
                    "referral_ulid": referral_ulid,
                    "resource_ulid": resource_ulid,
                    "need_key": need_key,
                    "outcome": outcome,
                },
            },
            "payload": payload,
        },
    )


def get_referral_compose_seed(
    *,
    entity_ulid: str,
    resource_ulid: str | None = None,
    need_key: str | None = None,
    match_bucket: str | None = None,
    method: str | None = None,
    synopsis: str | None = None,
    note: str | None = None,
) -> ReferralComposeView:
    ent = ensure_entity_ulid(entity_ulid)
    res_ulid = ensure_entity_ulid(resource_ulid) if resource_ulid else None
    need = (
        _require_one_of("need_key", need_key, NEEDS_CATEGORY_KEY)
        if need_key
        else None
    )
    bucket = (
        _require_nullable_one_of(
            "match_bucket", match_bucket, REFERRAL_MATCH_BUCKETS
        )
        if match_bucket is not None
        else None
    )
    meth = (
        _require_nullable_one_of("method", method, REFERRAL_METHODS)
        if method is not None
        else None
    )
    res_name = get_entity_display_name(res_ulid) if res_ulid else None
    return ReferralComposeView(
        entity_ulid=ent,
        resource_ulid=res_ulid,
        resource_name=res_name,
        need_key=need,
        need_label=_need_label(need) if need else None,
        match_bucket=bucket,
        method=meth,
        synopsis=(synopsis or "").strip(),
        note=(note or "").strip(),
    )


def get_referral_outcome_compose_seed(
    *,
    entity_ulid: str,
    referral_ulid: str | None = None,
    resource_ulid: str | None = None,
    need_key: str | None = None,
    outcome: str | None = None,
    synopsis: str | None = None,
    note: str | None = None,
) -> ReferralOutcomeComposeView:
    ent = ensure_entity_ulid(entity_ulid)
    ref_ulid = ensure_entity_ulid(referral_ulid) if referral_ulid else None
    res_ulid = ensure_entity_ulid(resource_ulid) if resource_ulid else None
    need = (
        _require_one_of("need_key", need_key, NEEDS_CATEGORY_KEY)
        if need_key
        else None
    )
    out = (
        _require_nullable_one_of("outcome", outcome, REFERRAL_OUTCOMES)
        if outcome is not None
        else None
    )
    res_name = get_entity_display_name(res_ulid) if res_ulid else None
    return ReferralOutcomeComposeView(
        entity_ulid=ent,
        referral_ulid=ref_ulid,
        resource_ulid=res_ulid,
        resource_name=res_name,
        need_key=need,
        need_label=_need_label(need) if need else None,
        outcome=out,
        synopsis=(synopsis or "").strip(),
        note=(note or "").strip(),
    )


def record_resource_referral(
    *,
    entity_ulid: str,
    resource_ulid: str,
    need_key: str,
    method: str,
    synopsis: str,
    actor_ulid: str,
    request_id: str,
    match_bucket: str | None = None,
    note: str | None = None,
) -> dict[str, str]:
    ent = ensure_entity_ulid(entity_ulid)
    res_ulid = ensure_entity_ulid(resource_ulid)
    act = ensure_actor_ulid(actor_ulid)
    rid = ensure_request_id(request_id)
    need = _require_one_of("need_key", need_key, NEEDS_CATEGORY_KEY)
    meth = _require_one_of("method", method, REFERRAL_METHODS)
    bucket = _require_nullable_one_of(
        "match_bucket", match_bucket, REFERRAL_MATCH_BUCKETS
    )
    syn = _require_len("synopsis", synopsis, max_len=512, required=True)
    note_clean = _require_len("note", note, max_len=4000)

    if db.session.get(Customer, ent) is None:
        raise LookupError("customer facet missing")

    resource_name = get_entity_display_name(res_ulid)
    referral_ulid = new_ulid()
    happened_at = now_iso8601_ms()
    history_kind, history_blob = _build_referral_history_entry(
        entity_ulid=ent,
        actor_ulid=act,
        happened_at=happened_at,
        referral_ulid=referral_ulid,
        resource_ulid=res_ulid,
        resource_name=resource_name,
        need_key=need,
        match_bucket=bucket,
        method=meth,
        synopsis=syn,
        note=note_clean,
    )
    history_ulid = append_history_entry(
        target_entity_ulid=ent,
        kind=history_kind,
        blob_json=history_blob,
        actor_ulid=act,
        request_id=rid,
    )

    event_bus.emit(
        domain="customers",
        operation="resource_referral_recorded",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs={
            "history_ulid": history_ulid,
            "referral_ulid": referral_ulid,
            "resource_ulid": res_ulid,
            "need_key": need,
            "method": meth,
            "match_bucket": bucket,
        },
        changed={"fields": ("customer_history.append", "referral")},
        happened_at_utc=happened_at,
    )
    return {
        "history_ulid": history_ulid,
        "referral_ulid": referral_ulid,
        "resource_ulid": res_ulid,
        "resource_name": resource_name,
        "need_key": need,
    }


def get_referral_seed_from_history(
    *, entity_ulid: str, history_ulid: str
) -> ReferralOutcomeComposeView:
    detail = get_customer_history_detail_public(
        entity_ulid=entity_ulid,
        history_ulid=history_ulid,
    )
    if detail.kind != "referral.created":
        raise ValueError("history entry is not a referral record")
    payload = detail.parsed.payload
    return get_referral_outcome_compose_seed(
        entity_ulid=entity_ulid,
        referral_ulid=str(payload.get("referral_ulid") or ""),
        resource_ulid=str(payload.get("resource_ulid") or ""),
        need_key=str(payload.get("need_key") or ""),
    )


def record_referral_outcome(
    *,
    entity_ulid: str,
    referral_ulid: str,
    resource_ulid: str,
    need_key: str,
    outcome: str,
    synopsis: str,
    actor_ulid: str,
    request_id: str,
    note: str | None = None,
) -> dict[str, str]:
    ent = ensure_entity_ulid(entity_ulid)
    ref_ulid = ensure_entity_ulid(referral_ulid)
    res_ulid = ensure_entity_ulid(resource_ulid)
    act = ensure_actor_ulid(actor_ulid)
    rid = ensure_request_id(request_id)
    need = _require_one_of("need_key", need_key, NEEDS_CATEGORY_KEY)
    out = _require_one_of("outcome", outcome, REFERRAL_OUTCOMES)
    syn = _require_len("synopsis", synopsis, max_len=512, required=True)
    note_clean = _require_len("note", note, max_len=4000)

    if db.session.get(Customer, ent) is None:
        raise LookupError("customer facet missing")

    resource_name = get_entity_display_name(res_ulid)
    happened_at = now_iso8601_ms()
    history_kind, history_blob = _build_referral_outcome_history_entry(
        entity_ulid=ent,
        actor_ulid=act,
        happened_at=happened_at,
        referral_ulid=ref_ulid,
        resource_ulid=res_ulid,
        resource_name=resource_name,
        need_key=need,
        outcome=out,
        synopsis=syn,
        note=note_clean,
    )
    history_ulid = append_history_entry(
        target_entity_ulid=ent,
        kind=history_kind,
        blob_json=history_blob,
        actor_ulid=act,
        request_id=rid,
    )

    event_bus.emit(
        domain="customers",
        operation="referral_outcome_recorded",
        request_id=rid,
        actor_ulid=act,
        target_ulid=ent,
        refs={
            "history_ulid": history_ulid,
            "referral_ulid": ref_ulid,
            "resource_ulid": res_ulid,
            "need_key": need,
            "outcome": out,
        },
        changed={
            "fields": (
                "customer_history.append",
                "referral.outcome",
            )
        },
        happened_at_utc=happened_at,
    )
    return {
        "history_ulid": history_ulid,
        "referral_ulid": ref_ulid,
        "resource_ulid": res_ulid,
        "resource_name": resource_name,
        "need_key": need,
        "outcome": out,
    }


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

    event_bus.emit(
        domain="customers",
        operation="customer_history_appended",
        request_id=request_id,
        actor_ulid=act,
        target_ulid=ent,
        refs={
            "history_ulid": row.ulid,
            "kind": kind,
            "source_slice": env.source_slice,
            "source_ref_ulid": env.source_ref_ulid,
        },
        changed={"fields": ("customer_history.append",)},
        happened_at_utc=env.happened_at_iso,
    )
    return row.ulid


def _unwrap_single_entity(item: Any, expected_type: type) -> Any:
    if isinstance(item, expected_type):
        return item

    seq: tuple[Any, ...] | list[Any] | None = None
    if isinstance(item, tuple):
        seq = item
    elif hasattr(item, "_mapping"):
        seq = tuple(item._mapping.values())
    elif hasattr(item, "_tuple"):
        seq = tuple(item._tuple())

    if seq and len(seq) >= 1 and isinstance(seq[0], expected_type):
        return seq[0]

    raise TypeError(f"unexpected paginated item shape: {type(item).__name__}")


def _unwrap_pair(
    item: Any, left_type: type, right_type: type
) -> tuple[Any, Any]:
    if (
        isinstance(item, tuple)
        and len(item) >= 2
        and isinstance(item[0], left_type)
        and isinstance(item[1], right_type)
    ):
        return item[0], item[1]

    seq: tuple[Any, ...] | None = None
    if hasattr(item, "_mapping"):
        seq = tuple(item._mapping.values())
    elif hasattr(item, "_tuple"):
        seq = tuple(item._tuple())

    if (
        seq
        and len(seq) >= 2
        and isinstance(seq[0], left_type)
        and isinstance(seq[1], right_type)
    ):
        return seq[0], seq[1]

    raise TypeError(f"unexpected paginated pair shape: {type(item).__name__}")


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

    def _unwrap_history(item: object) -> CustomerHistory:
        if isinstance(item, CustomerHistory):
            return item
        try:
            hist = item[0]  # type: ignore[index]
        except Exception as exc:
            raise TypeError(
                "expected CustomerHistory row from paginate()"
            ) from exc
        if not isinstance(hist, CustomerHistory):
            raise TypeError(
                "expected CustomerHistory as first selected value"
            )
        return hist

    def _to_row(item: Any) -> CustomerHistoryItemRow:
        h = _unwrap_history(item)
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

    def _unwrap_history_customer_pair(
        item: object,
    ) -> tuple[CustomerHistory, Customer]:
        try:
            h = item[0]  # type: ignore[index]
            c = item[1]  # type: ignore[index]
        except Exception as exc:
            raise TypeError(
                "expected (CustomerHistory, Customer) row from paginate()"
            ) from exc
        if not isinstance(h, CustomerHistory) or not isinstance(c, Customer):
            raise TypeError(
                "expected CustomerHistory and Customer in selected row"
            )
        return h, c

    def _to_row(item: Any) -> AdminInboxItemRow:
        h, c = _unwrap_history_customer_pair(item)
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
