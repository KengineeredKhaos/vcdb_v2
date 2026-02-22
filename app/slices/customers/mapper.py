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
    """
    Non-PII list & card projection for operator quick view.
    Database fields stored in tables as noted.
    """

    entity_ulid: str  # Customer table
    status: str  # Customer table
    intake_step: str  # Customer table
    intake_completed_at_iso: str | None  # Customer table
    needs_state: str  # Customer table
    tier1_min: int | None  # Customer table
    flag_tier1_immediate: bool  # Customer table
    watchlist: bool  # Customer table
    veteran_status: str  # CustomerEligibility table


@dataclass(frozen=True, slots=True)
class CustomerSummaryRow:
    """
    Row DTO for building list views
    """

    entity_ulid: str
    status: str
    intake_step: str
    intake_completed_at_iso: str | None
    needs_state: str
    tier1_min: int | None
    flag_tier1_immediate: bool
    watchlist: bool
    veteran_status: str


def map_customer_summary(r: CustomerSummaryRow) -> CustomerSummaryView:
    """
    Maps Rows to View DTO using comprehensions
    """
    return CustomerSummaryView(**asdict(r))


@dataclass(frozen=True, slots=True)
class CustomerDashboardView:
    """
    Operator-facing, aggregated, detailed view of
    Customer status, needs, intake and eligibility triage.
    Database fields stored in tables as noted.
    """

    entity_ulid: str  # Customer table
    status: str  # Customer table
    intake_step: str  # Customer table
    intake_completed_at_iso: str | None  # Customer table
    needs_state: str  # Customer table
    watchlist: bool  # Customer table

    veteran_status: str  # CustomerEligibility table
    homeless_status: str  # CustomerEligibility table

    assessment_version: int  # CustomerProfile table
    last_assessed_at_iso: str | None  # CustomerProfile table

    tier1_min: int | None  # Customer table
    tier2_min: int | None  # Customer table
    tier3_min: int | None  # Customer table
    flag_tier1_immediate: bool  # Customer table


@dataclass(frozen=True, slots=True)
class CustomerDashboardRow:
    """
    Row DTO for building list views
    """

    entity_ulid: str
    status: str
    intake_step: str
    intake_completed_at_iso: str | None
    needs_state: str
    watchlist: bool
    veteran_status: str
    homeless_status: str
    assessment_version: int
    last_assessed_at_iso: str | None
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool


def map_customer_dashboard(r: CustomerDashboardRow) -> CustomerDashboardView:
    """
    Maps Rows to View DTO using comprehensions
    """
    return CustomerDashboardView(**asdict(r))


@dataclass(frozen=True, slots=True)
class CustomerEligibilityView:
    """
    PII-free eligibility snapshot anchored by entity_ulid.
    """

    entity_ulid: str  # CustomerEligibility table
    veteran_status: str  # CustomerEligibility table
    veteran_method: str | None  # CustomerEligibility table
    homeless_status: str  # CustomerEligibility table
    approved_by_ulid: str | None  # CustomerEligibility table
    approved_at_iso: str | None  # CustomerEligibility table


@dataclass(frozen=True, slots=True)
class CustomerEligibilityRow:
    """
    Row DTO for building list views
    """

    entity_ulid: str
    veteran_status: str
    veteran_method: str | None
    homeless_status: str
    approved_by_ulid: str | None
    approved_at_iso: str | None


def map_customer_eligibility(
    r: CustomerEligibilityRow,
) -> CustomerEligibilityView:
    """
    Maps Rows to View DTO using comprehensions
    """
    return CustomerEligibilityView(**asdict(r))


@dataclass(frozen=True, slots=True)
class EnvelopeDTO:
    # Required by envelope schema
    schema_name: str  # e.g. "logistics.issuance_summary"
    schema_version: int  # e.g. 1
    title: str  # timeline title
    summary: str  # short synopsis (non-authoritative)
    severity: str  # "info" | "warn"
    happened_at_iso: str  # ISO 8601 string from envelope
    source_slice: str  # "customers" | "logistics" | "resources"

    # Optional in envelope
    source_ref_ulid: str | None
    created_by_actor_ulid: str | None
    public_tags: tuple[str, ...]
    admin_tags: tuple[str, ...]
    dedupe_key: str | None
    refs: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ParsedHistoryBlobDTO:
    envelope: EnvelopeDTO
    payload: dict[str, Any]  # producer-owned; Customers doesn't interpret


# -----------------
# Intake / Update
# Confirmation DTO
# -----------------


@dataclass(frozen=True, slots=True)
class ChangeSetDTO:
    entity_ulid: str
    created: bool
    noop: bool
    changed_fields: tuple[str, ...]
    next_step: str | None


# Public exports
__all__ = [
    "ChangeSetDTO",
    "CustomerSummaryView",
    "CustomerDashboardView",
    "CustomerEligibilityView",
    "EnvelopeDTO",
    "ParsedHistoryBlobDTO",
    "map_customer_summary",
    "map_customer_dashboard",
    "map_customer_eligibility",
]
