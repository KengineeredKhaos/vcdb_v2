# app/slices/customers/models.py

"""
Customers slice — customer card, eligibility factors, needs profile, and
timeline history.

Canonical intent:

- Customer (customer_customer) is a shallow customer card for lists and
  dashboards: coarse status, intake step, and cached service-readiness cues.
- CustomerEligibility is a facet (PK=FK) holding policy-relevant qualifiers
  (veteran/housing status + branch/era + verification method).
- CustomerProfile anchors the current needs assessment session.
- CustomerProfileRating stores the 12 category ratings for the CURRENT
  assessment_version and separates touched/assessed truth from the rating
  result.
- CustomerHistory is append-only narrative + structured snapshots. Each JSON
  blob is expected to be a CustomerHistory "envelope + payload" document.

Silent admin tags (review signals):

- Producers may include admin_tags in the envelope.
- Customers staff UI never renders admin_tags.
- CustomerHistory caches:
    has_admin_tags (bool), admin_tags_csv (text)
  so Admin can run a scheduled sweep job without JSON parsing gymnastics.

PII boundary:

- No PII lives here. Names/contacts/addresses/DOB/last4 remain in Entity.
- CustomerHistory payloads must not contain PII.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDPK, IsoTimestamps

# ---------------------------------------------------------------------------
# Stored-as-string enums (CHECK constraints values for reference only)
# ---------------------------------------------------------------------------

"""
_CUSTOMER_STATUS = ("intake", "active", "inactive", "archived")

_CUSTOMER_INTAKE_STEP = (
    "ensure",
    "eligibility",
    "needs_tier1",
    "needs_tier2",
    "needs_tier3",
    "review",
    "complete",
)

_PROFILE_RATING_VALUE = (
    "immediate",
    "marginal",
    "sufficient",
    "unknown",
    "not_applicable",
)

_HISTORY_SEVERITY = ("info", "warn")
"""

# ---------------------------------------------------------------------------
# Customer card (facet table: PK=FK)
# ---------------------------------------------------------------------------


class Customer(db.Model, IsoTimestamps):
    """
    FACET TABLE (anchor = entity_ulid)

    Shallow, denormalized "customer card" for dashboards/lists and workflow
    resume logic. No high-granularity profile details live here.
    """

    __tablename__ = "customer_customer"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("entity_entity.ulid", ondelete="CASCADE"),
        primary_key=True,
    )

    # coarse lifecycle/status posture
    status: Mapped[str] = mapped_column(
        String(24),
        default="intake",
        nullable=False,
        index=True,
    )

    # operator workflow step (navigation truth, not deep business truth)
    intake_step: Mapped[str] = mapped_column(
        String(32),
        default="ensure",
        nullable=False,
        index=True,
    )

    intake_completed_at_iso: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    # staged service-readiness truth
    eligibility_complete: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    entity_package_incomplete: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    tier1_assessed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    tier2_assessed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    tier3_assessed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    tier1_unlocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    tier2_unlocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    tier3_unlocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    assessment_complete: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    # escape hatch / operator review flag
    watchlist: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    # cached cues (derived from profile ratings + workflow rules)
    tier1_min: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    tier2_min: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    tier3_min: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    flag_tier1_immediate: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    eligibility: Mapped[CustomerEligibility] = relationship(
        "CustomerEligibility",
        back_populates="customer",
        uselist=False,
        cascade="all, delete-orphan",
    )

    profile: Mapped[CustomerProfile] = relationship(
        "CustomerProfile",
        back_populates="customer",
        uselist=False,
        cascade="all, delete-orphan",
    )

    histories: Mapped[list[CustomerHistory]] = relationship(
        "CustomerHistory",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('intake','active','inactive','archived')",
            name="ck_customer_status_enum",
        ),
        CheckConstraint(
            "intake_step IN ("
            "'ensure','eligibility','needs_tier1','needs_tier2','needs_tier3',"
            "'review','complete'"
            ")",
            name="ck_customer_intake_step_enum",
        ),
        CheckConstraint(
            "tier1_min IS NULL OR (tier1_min BETWEEN 1 AND 3)",
            name="ck_customer_tier1_range",
        ),
        CheckConstraint(
            "tier2_min IS NULL OR (tier2_min BETWEEN 1 AND 3)",
            name="ck_customer_tier2_range",
        ),
        CheckConstraint(
            "tier3_min IS NULL OR (tier3_min BETWEEN 1 AND 3)",
            name="ck_customer_tier3_range",
        ),
    )


# ---------------------------------------------------------------------------
# Eligibility factors (facet table: PK=FK)
# ---------------------------------------------------------------------------


class CustomerEligibility(db.Model, IsoTimestamps):
    """
    FACET TABLE (anchor = entity_ulid)

    Manual eligibility truth (non-PII). Needs-based hints (e.g. housing_immediate)
    are derived from profile ratings and are NOT stored here as authoritative
    state.

    Effective qualifier (used by downstream flows) should be computed as:
      housing_effective = (housing_status == 'unhoused') OR housing_immediate
    """

    __tablename__ = "customer_eligibility"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("customer_customer.entity_ulid", ondelete="CASCADE"),
        primary_key=True,
    )

    veteran_status: Mapped[str] = mapped_column(
        String(16),
        default="unknown",
        nullable=False,
        index=True,
    )

    veteran_method: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )

    branch: Mapped[str | None] = mapped_column(
        String(4),
        nullable=True,
        index=True,
    )

    era: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        index=True,
    )

    housing_status = db.Column(
        db.String(16),
        nullable=False,
        default="unknown",
    )

    approved_by_ulid: Mapped[str | None] = mapped_column(
        String(26),
        nullable=True,
    )

    approved_at_iso: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    customer: Mapped[Customer] = relationship(
        "Customer",
        back_populates="eligibility",
    )

    __table_args__ = (
        # If veteran_status != verified → method/approval fields must be NULL.
        CheckConstraint(
            "NOT (veteran_status != 'verified' AND "
            "(veteran_method IS NOT NULL OR approved_by_ulid IS NOT NULL OR "
            "approved_at_iso IS NOT NULL))",
            name="ck_cel_unverified_requires_nulls",
        ),
        # If verified → method is required.
        CheckConstraint(
            "NOT (veteran_status = 'verified' AND veteran_method IS NULL)",
            name="ck_cel_verified_requires_method",
        ),
        # If method='other' and verified → approved_by_ulid must be present.
        CheckConstraint(
            "NOT (veteran_status = 'verified' AND veteran_method = 'other' AND "
            "approved_by_ulid IS NULL)",
            name="ck_cel_other_requires_approval",
        ),
        CheckConstraint(
            "NOT (approved_by_ulid IS NOT NULL AND approved_at_iso IS NULL)",
            name="ck_cel_approval_requires_timestamp",
        ),
        CheckConstraint(
            "NOT (approved_at_iso IS NOT NULL AND approved_by_ulid IS NULL)",
            name="ck_cel_timestamp_requires_approver",
        ),
        CheckConstraint(
            housing_status.in_(("unknown", "housed", "unhoused")),
            name="ck_customer_elig_housing_status",
        ),
    )


# ---------------------------------------------------------------------------
# Needs profile (facet + child rows)
# ---------------------------------------------------------------------------


class CustomerProfile(db.Model, IsoTimestamps):
    """
    FACET TABLE (anchor = entity_ulid)

    Anchors the current needs assessment session. assessment_version starts at 0
    (no assessment yet). When assessment begins, version is incremented to 1 and
    the 12 rating rows are precreated with is_assessed=False and rating_value
    unset.
    """

    __tablename__ = "customer_profile"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("customer_customer.entity_ulid", ondelete="CASCADE"),
        primary_key=True,
    )

    assessment_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_assessed_at_iso: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    last_assessed_by_ulid: Mapped[str | None] = mapped_column(
        String(26),
        nullable=True,
    )

    customer: Mapped[Customer] = relationship(
        "Customer",
        back_populates="profile",
    )

    ratings: Mapped[list[CustomerProfileRating]] = relationship(
        "CustomerProfileRating",
        back_populates="profile",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "assessment_version >= 0",
            name="ck_cprof_assessment_version_nonneg",
        ),
    )


class CustomerProfileRating(db.Model, IsoTimestamps):
    """
    CHILD ROWS (versioned by assessment_version)

    Stores the 12 category ratings for the current assessment_version.
    Composite PK ensures exactly one row per category per version.
    """

    __tablename__ = "customer_profile_rating"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("customer_profile.entity_ulid", ondelete="CASCADE"),
        primary_key=True,
    )

    assessment_version: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    category_key: Mapped[str] = mapped_column(
        String(24),
        primary_key=True,
    )

    is_assessed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    rating_value: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        index=True,
    )

    profile: Mapped[CustomerProfile] = relationship(
        "CustomerProfile",
        back_populates="ratings",
    )

    __table_args__ = (
        CheckConstraint(
            "assessment_version >= 1",
            name="ck_cpr_assessment_version_pos",
        ),
        CheckConstraint(
            "rating_value IS NULL OR rating_value IN ("
            "'immediate','marginal','sufficient','unknown','not_applicable'"
            ")",
            name="ck_cpr_rating_value_enum",
        ),
        CheckConstraint(
            "NOT (is_assessed = 0 AND rating_value IS NOT NULL)",
            name="ck_cpr_unassessed_requires_null_rating",
        ),
    )


# ---------------------------------------------------------------------------
# Customer history (append-only, narrative + snapshots)
# ---------------------------------------------------------------------------


class CustomerHistory(db.Model, ULIDPK, IsoTimestamps):
    """
    Append-only timeline receptacle.

    data_json holds an "envelope + payload" blob. We cache a few envelope fields
    as columns to support fast "quick peek" timeline views without cross-slice
    schema retrieval.

    Silent admin flags:
      - has_admin_tags/admin_tags_csv are cached for Admin sweep jobs.
      - Customers staff UI never renders admin_tags.
    """

    __tablename__ = "customer_history"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("customer_customer.entity_ulid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    happened_at_iso: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    source_slice: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    source_ref_ulid: Mapped[str | None] = mapped_column(
        String(26),
        nullable=True,
        index=True,
    )

    # Cached envelope metadata (for UI + sweeps).
    schema_name: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    title: Mapped[str | None] = mapped_column(
        String(140),
        nullable=True,
    )

    summary: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    severity: Mapped[str] = mapped_column(
        String(12),
        default="info",
        nullable=False,
        index=True,
    )

    public_tags_csv: Mapped[str | None] = mapped_column(
        String(240),
        nullable=True,
    )

    has_admin_tags: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    admin_tags_csv: Mapped[str | None] = mapped_column(
        String(240),
        nullable=True,
    )

    created_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26),
        nullable=True,
    )

    data_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    customer: Mapped[Customer] = relationship(
        "Customer",
        back_populates="histories",
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info','warn')",
            name="ck_chist_severity_enum",
        ),
    )
