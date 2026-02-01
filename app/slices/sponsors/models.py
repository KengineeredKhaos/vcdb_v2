# app/slices/sponsors/models.py

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDPK, IsoTimestamps


class Sponsor(db.Model, IsoTimestamps):
    """
    FACET TABLE (anchor = entity_ulid):

    One row per Entity (typically EntityOrg) that acts as a service provider.
    Primary key is entity_ulid (same ULID as the Entity row).
    """

    __tablename__ = "sponsor_sponsor"

    # Facet PK == FK to Entity.ulid
    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("entity_entity.ulid", ondelete="CASCADE"),
        primary_key=True,
    )
    onboard_step: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True
    )
    admin_review_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    readiness_status: Mapped[str] = mapped_column(
        String(16), default="draft", nullable=False, index=True
    )  # draft|review|active|suspended
    mou_status: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False, index=True
    )  # none|pending|active|expired|terminated

    first_seen_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_touch_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    capability_last_update_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    pledge_last_update_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # -------------
    # Relationships
    # -------------

    histories: Mapped[list["SponsorHistory"]] = relationship(
        "SponsorHistory",
        back_populates="sponsor",
        cascade="all, delete-orphan",
    )
    capabilities: Mapped[list["SponsorCapabilityIndex"]] = relationship(
        "SponsorCapabilityIndex",
        back_populates="sponsor",
        cascade="all, delete-orphan",
    )
    pledges: Mapped[list["SponsorPledgeIndex"]] = relationship(
        "SponsorPledgeIndex",
        back_populates="sponsor",
        cascade="all, delete-orphan",
    )
    pocs: Mapped[list["SponsorPOC"]] = relationship(
        "SponsorPOC",
        back_populates="sponsor",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    funding_prospects: Mapped[list["FundingProspect"]] = relationship(
        "FundingProspect",
        back_populates="sponsor",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # PK already implies uniqueness; this index helps some query planners.
        Index("ix_sponsor_entity_ulid", "entity_ulid"),
    )


class SponsorHistory(db.Model, ULIDPK, IsoTimestamps):
    """
    Privacy A (strict). Stores snapshots for:
      - section='sponsor:capability:v1' : flattened "domain.key" -> {has:bool,note?:str}
      - section='sponsor:pledge:v1'     : {pledge_ulid:str -> pledge_payload}
    """

    __tablename__ = "sponsor_history"

    sponsor_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("sponsor_sponsor.entity_ulid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_json: Mapped[str] = mapped_column(String, nullable=False)

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor", back_populates="histories"
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_sponsor_hist_version_pos"),
    )


class SponsorCapabilityIndex(db.Model, ULIDPK, IsoTimestamps):
    """
    Projection for fast capability queries (names only, no notes).
    """

    __tablename__ = "sponsor_capability_index"

    sponsor_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("sponsor_sponsor.entity_ulid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    domain: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor", back_populates="capabilities"
    )

    __table_args__ = (
        UniqueConstraint(
            "sponsor_entity_ulid",
            "domain",
            "key",
            name="uq_sponsor_cap_idx_triplet",
        ),
    )


class FundingProspect(db.Model, ULIDPK, IsoTimestamps):
    """
    Pre-pledge fundraising prospect linked to a Sponsor.

    This models “we think this Sponsor might fund X for Y project type with
    an estimated range”, without promising that the money will ever arrive.

    All fields are PII-free and keyed by ULIDs and normalized governance keys.
    Detailed notes should live in external docs or a future snapshot store,
    not here.
    """

    __tablename__ = "sponsor_funding_prospect"

    sponsor_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("sponsor_sponsor.entity_ulid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Governance-backed keys (validated by policy_semantics in services)
    project_type_key: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # e.g. "stand_down", "operations"
    fund_archetype_key: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # e.g. "grant_advance", "general_unrestricted"

    # Human-facing short label, for UIs/reports (PII-free)
    label: Mapped[str] = mapped_column(
        String(80), nullable=False
    )  # e.g. "Elks Freedom Grant 2025"

    # Coarse estimate range (cents); both optional but non-negative if present
    est_min_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_max_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Confidence 0-100 (rough probability this will land)
    confidence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50
    )

    # Lifecycle of the prospect (no money yet, just pipeline state)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="prospect",
        index=True,
    )  # prospect|approach|active|closed|lost

    # Realized total so far (from Finance Journal), in integer cents.
    # This is updated by Finance when actual donations are recorded.
    realized_total_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor",
        back_populates="funding_prospects",
    )

    __table_args__ = (
        CheckConstraint(
            "est_min_cents IS NULL OR est_min_cents >= 0",
            name="ck_funding_prospect_min_nonneg",
        ),
        CheckConstraint(
            "est_max_cents IS NULL OR est_max_cents >= 0",
            name="ck_funding_prospect_max_nonneg",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_funding_prospect_confidence_range",
        ),
        CheckConstraint(
            # if both bounds present, enforce min <= max
            "est_min_cents IS NULL OR est_max_cents IS NULL OR est_min_cents <= est_max_cents",
            name="ck_funding_prospect_min_le_max",
        ),
    )


class SponsorPledgeIndex(db.Model, ULIDPK, IsoTimestamps):
    """
    Projection summary for pledges (no sensitive notes; minimal numbers for dashboards).
    """

    __tablename__ = "sponsor_pledge_index"

    sponsor_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("sponsor_sponsor.entity_ulid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    pledge_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True, unique=True
    )

    type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # cash | in_kind
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # proposed|active|fulfilled|cancelled
    has_restriction: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    est_value_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # integer cents or units (MVP int)
    currency: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # USD etc.

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor", back_populates="pledges"
    )


class SponsorPOC(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "sponsor_poc"

    sponsor_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("sponsor_sponsor.entity_ulid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("entity_entity.ulid", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    relation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="poc"
    )

    scope: Mapped[str] = mapped_column(String(24), nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    org_role: Mapped[str] = mapped_column(String(64), nullable=True)

    valid_from_utc: Mapped[str] = mapped_column(String(30), nullable=True)
    valid_to_utc: Mapped[str] = mapped_column(String(30), nullable=True)

    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # -------------
    # Relationships
    # -------------

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor",
        back_populates="pocs",
    )

    __table_args__ = (
        UniqueConstraint(
            "sponsor_entity_ulid",
            "person_entity_ulid",
            "relation",
            "scope",
            name="uq_sponsor_poc_sponsor_person_scope",
        ),
        Index(
            "ix_sponsor_poc_org_scope_rank",
            "sponsor_entity_ulid",
            "relation",
            "scope",
            "rank",
        ),
        Index(
            "ix_sponsor_poc_primary",
            "sponsor_entity_ulid",
            "relation",
            "scope",
            "is_primary",
        ),
        CheckConstraint(
            "rank >= 0 AND rank <= 99", name="ck_sponsor_poc_rank_range"
        ),
    )
