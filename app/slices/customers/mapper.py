# app/slices/customers/mapper.py
"""
Slice-local projection layer (Customers).

- Pure mapping only: no DB reads/writes, no commits/rollbacks, no emits.
- Non-PII: Customer slice mappers must not expose Entity PII.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CustomerProviderNeedOptionView:
    key: str
    label: str
    tier: int


@dataclass(frozen=True, slots=True)
class CustomerProviderNeedOptionRow:
    key: str
    label: str
    tier: int


def map_customer_provider_need_option(
    r: CustomerProviderNeedOptionRow,
) -> CustomerProviderNeedOptionView:
    return CustomerProviderNeedOptionView(**asdict(r))


@dataclass(frozen=True, slots=True)
class CustomerProviderMatchItemView:
    entity_ulid: str
    display_name: str
    readiness_status: str
    mou_status: str
    matched_capability_keys: tuple[str, ...]
    bucket: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CustomerProviderMatchItemRow:
    entity_ulid: str
    display_name: str
    readiness_status: str
    mou_status: str
    matched_capability_keys: tuple[str, ...]
    bucket: str
    reason_codes: tuple[str, ...]


def map_customer_provider_match_item(
    r: CustomerProviderMatchItemRow,
) -> CustomerProviderMatchItemView:
    return CustomerProviderMatchItemView(**asdict(r))


@dataclass(frozen=True, slots=True)
class CustomerProviderMatchView:
    entity_ulid: str
    display_name: str
    dash: CustomerDashboardView
    need_options: tuple[CustomerProviderNeedOptionView, ...]
    need_key: str | None
    need_label: str | None
    need_tier: int | None
    need_rating: str | None
    tier_priority: int | None
    customer_gate: str | None
    blocked_reason: str | None
    operator_cautions: tuple[str, ...]
    exact_matches: tuple[CustomerProviderMatchItemView, ...]
    adjacent_matches: tuple[CustomerProviderMatchItemView, ...]
    review_matches: tuple[CustomerProviderMatchItemView, ...]
    as_of_iso: str | None


@dataclass(frozen=True, slots=True)
class CustomerProviderMatchRow:
    entity_ulid: str
    display_name: str
    dash: CustomerDashboardRow | CustomerDashboardView
    need_options: tuple[CustomerProviderNeedOptionView, ...]
    need_key: str | None
    need_label: str | None
    need_tier: int | None
    need_rating: str | None
    tier_priority: int | None
    customer_gate: str | None
    blocked_reason: str | None
    operator_cautions: tuple[str, ...]
    exact_matches: tuple[CustomerProviderMatchItemView, ...]
    adjacent_matches: tuple[CustomerProviderMatchItemView, ...]
    review_matches: tuple[CustomerProviderMatchItemView, ...]
    as_of_iso: str | None


def map_customer_provider_match(
    r: CustomerProviderMatchRow,
) -> CustomerProviderMatchView:
    dash = (
        r.dash
        if isinstance(r.dash, CustomerDashboardView)
        else map_customer_dashboard(r.dash)
    )
    return CustomerProviderMatchView(
        entity_ulid=r.entity_ulid,
        display_name=r.display_name,
        dash=dash,
        need_options=r.need_options,
        need_key=r.need_key,
        need_label=r.need_label,
        need_tier=r.need_tier,
        need_rating=r.need_rating,
        tier_priority=r.tier_priority,
        customer_gate=r.customer_gate,
        blocked_reason=r.blocked_reason,
        operator_cautions=r.operator_cautions,
        exact_matches=r.exact_matches,
        adjacent_matches=r.adjacent_matches,
        review_matches=r.review_matches,
        as_of_iso=r.as_of_iso,
    )


@dataclass(frozen=True, slots=True)
class CustomerSummaryView:
    entity_ulid: str
    status: str
    intake_step: str
    intake_completed_at_iso: str | None
    eligibility_complete: bool
    entity_package_incomplete: bool
    tier1_assessed: bool
    tier2_assessed: bool
    tier3_assessed: bool
    tier1_unlocked: bool
    tier2_unlocked: bool
    tier3_unlocked: bool
    assessment_complete: bool
    tier1_min: int | None
    flag_tier1_immediate: bool
    watchlist: bool
    veteran_status: str


@dataclass(frozen=True, slots=True)
class CustomerSummaryRow:
    entity_ulid: str
    status: str
    intake_step: str
    intake_completed_at_iso: str | None
    eligibility_complete: bool
    entity_package_incomplete: bool
    tier1_assessed: bool
    tier2_assessed: bool
    tier3_assessed: bool
    tier1_unlocked: bool
    tier2_unlocked: bool
    tier3_unlocked: bool
    assessment_complete: bool
    tier1_min: int | None
    flag_tier1_immediate: bool
    watchlist: bool
    veteran_status: str


def map_customer_summary(r: CustomerSummaryRow) -> CustomerSummaryView:
    return CustomerSummaryView(**asdict(r))


@dataclass(frozen=True, slots=True)
class CustomerDashboardView:
    entity_ulid: str
    status: str
    intake_step: str
    intake_completed_at_iso: str | None
    watchlist: bool
    eligibility_complete: bool
    entity_package_incomplete: bool
    veteran_status: str
    housing_status: str
    assessment_version: int
    last_assessed_at_iso: str | None
    tier1_assessed: bool
    tier2_assessed: bool
    tier3_assessed: bool
    tier1_unlocked: bool
    tier2_unlocked: bool
    tier3_unlocked: bool
    assessment_complete: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool


@dataclass(frozen=True, slots=True)
class CustomerDashboardRow:
    entity_ulid: str
    status: str
    intake_step: str
    intake_completed_at_iso: str | None
    watchlist: bool
    eligibility_complete: bool
    entity_package_incomplete: bool
    veteran_status: str
    housing_status: str
    assessment_version: int
    last_assessed_at_iso: str | None
    tier1_assessed: bool
    tier2_assessed: bool
    tier3_assessed: bool
    tier1_unlocked: bool
    tier2_unlocked: bool
    tier3_unlocked: bool
    assessment_complete: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool


@dataclass(frozen=True, slots=True)
class ReferralComposeView:
    entity_ulid: str
    resource_ulid: str | None
    resource_name: str | None
    need_key: str | None
    need_label: str | None
    match_bucket: str | None
    method: str | None
    synopsis: str
    note: str


@dataclass(frozen=True, slots=True)
class ReferralOutcomeComposeView:
    entity_ulid: str
    referral_ulid: str | None
    resource_ulid: str | None
    resource_name: str | None
    need_key: str | None
    need_label: str | None
    outcome: str | None
    synopsis: str
    note: str


def map_customer_dashboard(r: CustomerDashboardRow) -> CustomerDashboardView:
    return CustomerDashboardView(**asdict(r))


@dataclass(frozen=True, slots=True)
class CustomerEligibilityView:
    entity_ulid: str
    veteran_status: str
    veteran_method: str | None
    branch: str | None
    era: str | None
    housing_status: str
    approved_by_ulid: str | None
    approved_at_iso: str | None


@dataclass(frozen=True, slots=True)
class CustomerEligibilityRow:
    entity_ulid: str
    veteran_status: str
    veteran_method: str | None
    branch: str | None
    era: str | None
    housing_status: str
    approved_by_ulid: str | None
    approved_at_iso: str | None


def map_customer_eligibility(
    r: CustomerEligibilityRow,
) -> CustomerEligibilityView:
    return CustomerEligibilityView(**asdict(r))


@dataclass(frozen=True, slots=True)
class EnvelopeDTO:
    schema_name: str
    schema_version: int
    title: str
    summary: str
    severity: str
    happened_at_iso: str
    source_slice: str
    source_ref_ulid: str | None
    created_by_actor_ulid: str | None
    public_tags: tuple[str, ...]
    admin_tags: tuple[str, ...]
    dedupe_key: str | None
    refs: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ParsedHistoryBlobDTO:
    envelope: EnvelopeDTO
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CustomerHistoryItemView:
    ulid: str
    entity_ulid: str
    kind: str
    happened_at_iso: str
    severity: str
    title: str | None
    summary: str | None
    source_slice: str
    source_ref_ulid: str | None
    public_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CustomerHistoryItemRow:
    ulid: str
    entity_ulid: str
    kind: str
    happened_at_iso: str
    severity: str
    title: str | None
    summary: str | None
    source_slice: str
    source_ref_ulid: str | None
    public_tags: tuple[str, ...]


def map_customer_history_item(
    r: CustomerHistoryItemRow,
) -> CustomerHistoryItemView:
    return CustomerHistoryItemView(**asdict(r))


@dataclass(frozen=True, slots=True)
class CustomerHistoryDetailView:
    ulid: str
    entity_ulid: str
    kind: str
    happened_at_iso: str
    parsed: ParsedHistoryBlobDTO


@dataclass(frozen=True, slots=True)
class CustomerHistoryDetailRow:
    ulid: str
    entity_ulid: str
    kind: str
    happened_at_iso: str
    parsed: ParsedHistoryBlobDTO


def map_customer_history_detail(
    r: CustomerHistoryDetailRow,
) -> CustomerHistoryDetailView:
    return CustomerHistoryDetailView(
        ulid=r.ulid,
        entity_ulid=r.entity_ulid,
        kind=r.kind,
        happened_at_iso=r.happened_at_iso,
        parsed=r.parsed,
    )


@dataclass(frozen=True, slots=True)
class AdminInboxItemView:
    history_ulid: str
    entity_ulid: str
    customer_status: str
    watchlist: bool
    tier1_min: int | None
    flag_tier1_immediate: bool
    happened_at_iso: str
    severity: str
    title: str | None
    summary: str | None
    admin_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdminInboxItemRow:
    history_ulid: str
    entity_ulid: str
    customer_status: str
    watchlist: bool
    tier1_min: int | None
    flag_tier1_immediate: bool
    happened_at_iso: str
    severity: str
    title: str | None
    summary: str | None
    admin_tags: tuple[str, ...]


def map_admin_inbox_item(r: AdminInboxItemRow) -> AdminInboxItemView:
    return AdminInboxItemView(**asdict(r))


@dataclass(frozen=True, slots=True)
class ChangeSetDTO:
    entity_ulid: str
    created: bool
    noop: bool
    changed_fields: tuple[str, ...]
    next_step: str | None


__all__ = [
    "ChangeSetDTO",
    "CustomerHistoryItemView",
    "CustomerHistoryDetailView",
    "AdminInboxItemView",
    "CustomerSummaryView",
    "CustomerDashboardView",
    "CustomerEligibilityView",
    "CustomerProviderNeedOptionView",
    "CustomerProviderMatchItemView",
    "CustomerProviderMatchView",
    "EnvelopeDTO",
    "ParsedHistoryBlobDTO",
    "ReferralComposeView",
    "ReferralOutcomeComposeView",
    "map_customer_history_item",
    "map_customer_history_detail",
    "map_admin_inbox_item",
    "map_customer_summary",
    "map_customer_dashboard",
    "map_customer_eligibility",
    "map_customer_provider_need_option",
    "map_customer_provider_match_item",
    "map_customer_provider_match",
]
