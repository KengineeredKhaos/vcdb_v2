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
    "EnvelopeDTO",
    "ParsedHistoryBlobDTO",
    "map_customer_history_item",
    "map_customer_history_detail",
    "map_admin_inbox_item",
    "map_customer_summary",
    "map_customer_dashboard",
    "map_customer_eligibility",
]
