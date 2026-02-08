# app/slices/customers/mapper.py
"""
Slice-local projection layer (Customers).

- Pure mapping only: no DB reads/writes, no commits/rollbacks, no emits.
- Non-PII: Customer slice mappers must not expose Entity PII.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


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
class CustomerEligibilityView:
    """PII-free eligibility/cadence cues for cross-slice gating."""

    entity_ulid: str
    is_veteran_verified: bool
    veteran_method: str | None
    approved_by_ulid: str | None
    approved_at_utc: str | None
    is_homeless_verified: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
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
