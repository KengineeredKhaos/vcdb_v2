# app/slices/customers/models.py

"""
Customers slice — core customer record, sensitive history snapshots, and
non-PII eligibility qualifiers.

This module defines three models that together represent a "customer" from the
app's point of view:

* Customer
    One row per person who is treated as a customer in VCDB. It is keyed by
    `entity_ulid` (from the Entity slice) and stores denormalized, UI-friendly
    cues only: tier thresholds, watch/flag status, lifecycle status, and a
    handful of ISO8601 timestamps for "first seen", "last touch", and needs
    updates. No high-granularity profile details live here; this table is
    deliberately shallow and optimized for dashboards, lists, and quick filters.
* CustomerHistory
    Privacy-A snapshot store. This is where sensitive profile data actually
    lives, in sectioned JSON blobs (for example: "profile:needs:tier1"). Each
    row is a versioned snapshot for a single customer/section. Routes and
    services should treat this as the source of truth for "what did this part
    of the profile look like at that time?" and avoid leaking its contents into
    logs, ledger, or other slices.
* CustomerEligibility
    Non-PII eligibility and cadence qualifiers, one row per Customer. This holds
    coarse, policy-relevant flags such as "is veteran verified", how that was
    verified, homelessness verification, and tier minima. Values are normalized,
    constrained via CHECK constraints, and safe to expose via contracts to
    Governance, Logistics, Resources, etc., when those slices need to evaluate
    issuance/referral policy without touching raw profile data.

Ownership and boundaries:

* The Customers slice owns these tables and is responsible for enforcing the
  PII boundary: detailed profile values go into CustomerHistory; only coarse,
  derived indicators are surfaced in Customer and CustomerEligibility.
* Other slices should reference customers by `customer_ulid` (never by internal
  structure here) and interact through extensions/contracts, not by importing
  these models directly.
* Ledger and logging must continue to refer only to ULIDs and non-PII flags,
  never to raw snapshot contents.

In short, this module gives us a clean separation between the lightweight
"customer card" we show to staff, the sensitive historical snapshots we must
protect, and the normalized eligibility signals that downstream policy engines
consume.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


class Customer(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "customer_customer"

    # one Customer per Entity
    entity_ulid: Mapped[str] = ULIDFK("entity_entity", index=True)
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_customer_entity"),
    )

    # derived cues (denormalized for dashboards/lists)
    tier1_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    tier2_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    tier3_min: Mapped[int | None] = mapped_column(Integer, nullable=True)

    flag_tier1_immediate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    watchlist: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # lifecycle/status
    status: Mapped[str] = mapped_column(
        String(24), default="active", nullable=False, index=True
    )

    # ops timestamps (denormalized; for fast UI)
    first_seen_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_touch_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # needs tracking helpers
    last_needs_update_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_needs_tier_updated: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # "tier1"|"tier2"|"tier3"
    flag_reason: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )  # e.g. "food=1"
    watchlist_since_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    histories: Mapped[list["CustomerHistory"]] = relationship(
        "CustomerHistory",
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class CustomerHistory(db.Model, ULIDPK, IsoTimestamps):
    """
    Privacy A (strict): stores sensitive snapshots. Values live ONLY here.
    """

    __tablename__ = "customer_history"

    customer_ulid: Mapped[str] = ULIDFK("customer_customer", index=True)
    section: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # 'profile:needs:tier1'|tier2|tier3
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    data_json: Mapped[str] = mapped_column(String, nullable=False)

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="histories"
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_history_version_pos"),
    )


class CustomerEligibility(db.Model, ULIDPK, IsoTimestamps):
    """
    Non-PII eligibility/cadence qualifiers (1 row per Customer).
    Matches Customers slice conventions: ULID PK + ISO8601-ms timestamps.
    """

    __tablename__ = "customer_eligibility"

    # FK to Customer (not Entity) to stay within slice and align with your pattern
    customer_ulid: Mapped[str] = ULIDFK("customer_customer", index=True)

    # Verified qualifiers (coarse booleans)
    is_veteran_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    veteran_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # dd214|va_id|state_dl_veteran|other
    approved_by_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    approved_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    is_homeless_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # Coarse needs tiers (1=immediate, 2=marginal, 3=sufficient; None unknown)
    tier1_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    tier2_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    tier3_min: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "customer_ulid", name="uq_customer_eligibility_customer"
        ),
        CheckConstraint(
            "tier1_min IS NULL OR (tier1_min BETWEEN 1 AND 3)",
            name="ck_el_tier1_range",
        ),
        CheckConstraint(
            "tier2_min IS NULL OR (tier2_min BETWEEN 1 AND 3)",
            name="ck_el_tier2_range",
        ),
        CheckConstraint(
            "tier3_min IS NULL OR (tier3_min BETWEEN 1 AND 3)",
            name="ck_el_tier3_range",
        ),
        # enum guard
        CheckConstraint(
            "veteran_method IS NULL OR veteran_method IN "
            "('dd214','va_id','state_dl_veteran','other')",
            name="ck_ce_veteran_method_enum",
        ),
        # if not verified → all method/approval fields must be NULL
        CheckConstraint(
            "NOT (is_veteran_verified = 0 AND "
            "(veteran_method IS NOT NULL OR approved_by_ulid IS NOT NULL OR approved_at_utc IS NOT NULL))",
            name="ck_ce_unverified_requires_nulls",
        ),
        # if method='other' and verified → approved_by_ulid must be present
        CheckConstraint(
            "NOT (is_veteran_verified = 1 AND veteran_method = 'other' AND approved_by_ulid IS NULL)",
            name="ck_ce_other_requires_approval",
        ),
    )
