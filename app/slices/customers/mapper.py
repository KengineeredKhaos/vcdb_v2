# app/slices/customers/mapper.py
"""
Slice-local projection layer (Customers).

- Pure mapping only: no DB reads/writes, no commits/rollbacks, no emits.
- Non-PII: Customer slice mappers must not expose Entity PII.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CustomerSummaryView:
    """Non-PII list/card projection for operators."""

    entity_ulid: str
    status: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool
    watchlist: bool
    watchlist_since_utc: str | None
    first_seen_utc: str | None
    last_touch_utc: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


@dataclass(frozen=True)
class CustomerDashboardView:
    """Operator-facing aggregated read (still non-PII)."""

    entity_ulid: str
    status: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool
    flag_reason: str | None
    watchlist: bool
    watchlist_since_utc: str | None
    tier_factors: Mapping[str, Mapping[str, object]]
    first_seen_utc: str | None
    last_touch_utc: str | None
    last_needs_update_utc: str | None
    last_needs_tier_updated: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


@dataclass(frozen=True)
class CustomerEligibilityView:
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


def map_customer_summary(c) -> CustomerSummaryView:
    """
    Map a Customer ORM row to a non-PII summary view.

    NOTE: 'c' is intentionally untyped here so the mapper module stays
    import-light; the Customers services should pass the correct ORM type.
    """
    return CustomerSummaryView(
        entity_ulid=c.entity_ulid,
        status=c.status,
        tier1_min=c.tier1_min,
        tier2_min=c.tier2_min,
        tier3_min=c.tier3_min,
        flag_tier1_immediate=bool(c.flag_tier1_immediate),
        watchlist=bool(c.watchlist),
        watchlist_since_utc=getattr(c, "watchlist_since_utc", None),
        first_seen_utc=getattr(c, "first_seen_utc", None),
        last_touch_utc=getattr(c, "last_touch_utc", None),
        created_at_utc=getattr(c, "created_at_utc", None),
        updated_at_utc=getattr(c, "updated_at_utc", None),
    )


def map_customer_dashboard(
    c, tier_factors: Mapping[str, Mapping[str, object]]
) -> CustomerDashboardView:
    return CustomerDashboardView(
        entity_ulid=c.entity_ulid,
        status=getattr(c, "status", ""),
        tier1_min=getattr(c, "tier1_min", None),
        tier2_min=getattr(c, "tier2_min", None),
        tier3_min=getattr(c, "tier3_min", None),
        flag_tier1_immediate=bool(getattr(c, "flag_tier1_immediate", False)),
        flag_reason=getattr(c, "flag_reason", None),
        watchlist=bool(getattr(c, "watchlist", False)),
        watchlist_since_utc=getattr(c, "watchlist_since_utc", None),
        tier_factors=tier_factors,
        first_seen_utc=getattr(c, "first_seen_utc", None),
        last_touch_utc=getattr(c, "last_touch_utc", None),
        last_needs_update_utc=getattr(c, "last_needs_update_utc", None),
        last_needs_tier_updated=getattr(c, "last_needs_tier_updated", None),
        created_at_utc=getattr(c, "created_at_utc", None),
        updated_at_utc=getattr(c, "updated_at_utc", None),
    )


def map_customer_eligibility(e) -> CustomerEligibilityView:
    def _g(name: str, default=None):
        return getattr(e, name, default)

    created = _g("created_at_utc", None) or _g("created_at", None)
    updated = _g("updated_at_utc", None) or _g("updated_at", None)

    return CustomerEligibilityView(
        entity_ulid=(
            getattr(e, "customer_entity_ulid", None) or _g("entity_ulid", "")
        )
        or "",
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


# Public exports
__all__ = [
    "CustomerSummaryView",
    "CustomerDashboardView",
    "CustomerEligibilityView",
    "EnvelopeDTO",
    "ParsedHistoryBlobDTO",
    "map_customer_summary",
    "map_customer_dashboard",
    "map_customer_eligibility",
]
