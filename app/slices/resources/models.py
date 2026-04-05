# app/slices/resources/models.py

"""
Resources slice — service-providing orgs, capability snapshots, and POCs.

This module models organizations that act as service providers ("Resources") in
VCDB v2. Each Resource is backed by a single EntityOrg record and carries its
own lifecycle flags (readiness, MOU status) plus capability metadata and
points-of-contact. No PII is stored here; people/organizations are always
referenced by their Entity ULIDs.

Models:

* Resource
    One row per service-providing org, keyed by `entity_ulid` from EntityOrg.
    Tracks operational state (admin_review_required, readiness_status,
    mou_status) and a few ISO8601 timestamps for first_seen, last_touch, and
    last capability update. This is the anchor record that other slices use
    when referring to a provider.
* ResourceHistory
    Privacy-A snapshot store of capability details. Each row captures a
    versioned JSON blob (booleans + notes) for a fixed section
    ('resource:capability:v1'). Services write here on capability upsert so we
    have an auditable record of what the org said it could do at a given time,
    without leaking notes into search indexes or other slices. ResourceHistory
    remains Resource-owned private truth; it is not a second CustomerHistory
    producer.
* ResourceCapabilityIndex
    A materialized "current capabilities" index for fast search/filter. It
    stores only (resource_ulid, domain, key, active) — names/flags, no notes.
    Services rebuild this index from ResourceHistory so search endpoints can
    answer "which orgs provide X?" without touching the sensitive snapshot
    data.
* ResourcePOC
    Slice-owned linkage between a Resource and a person (EntityPerson) serving
    as a point-of-contact for an EntityOrg. Stores only ULIDs plus
    Governance-constrained metadata such as relation, scope, rank, and org_role,
    along with validity windows and primary/active flags. This lets Resources
    expose and order POCs without duplicating names, emails, or phone numbers.

Ownership and boundaries:

* The Resources slice owns these tables and is responsible for keeping PII in
  the Entity slice and sensitive notes in ResourceHistory; other slices should
  interact via services/contracts using ULIDs and capability keys, not by
  importing these models directly.
* Resources owns its local service vocabulary (domains/keys), operational
  readiness semantics, and POC ordering rules. Governance stays focused on
  board-level policy, authorization, and records-retention decisions rather
  than day-to-day service taxonomy.
* Ledger and logging must continue to record only ULIDs and normalized keys;
  any detailed narrative about capabilities or MOUs lives in snapshot JSON or
  external documents, not in logs or the ledger.

In short, this module gives us a clean separation between a provider org's
lifecycle state, its sensitive capability snapshots, a searchable capability
index, and slice-local POC links back to Entity identities.
"""

# app/slices/resources/models.py

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDPK, IsoTimestamps


class Resource(db.Model, IsoTimestamps):
    """
    FACET TABLE (anchor = entity_ulid):

    One row per Entity (typically EntityOrg) that acts as a service provider.
    Primary key is entity_ulid (same ULID as the Entity row).
    """

    __tablename__ = "resource_resource"

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
    )
    mou_status: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False, index=True
    )

    first_seen_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_touch_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    capability_last_update_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # Relationships
    histories: Mapped[list[ResourceHistory]] = relationship(
        "ResourceHistory",
        back_populates="resource",
        cascade="all, delete-orphan",
    )
    capabilities: Mapped[list[ResourceCapabilityIndex]] = relationship(
        "ResourceCapabilityIndex",
        back_populates="resource",
        cascade="all, delete-orphan",
    )
    pocs: Mapped[list[ResourcePOC]] = relationship(
        "ResourcePOC",
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # PK already implies uniqueness; this index helps some query planners.
        Index("ix_resource_entity_ulid", "entity_ulid"),
    )


class ResourceHistory(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "resource_history"

    resource_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("resource_resource.entity_ulid", ondelete="CASCADE"),
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

    resource: Mapped[Resource] = relationship(
        "Resource", back_populates="histories"
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_res_history_version_pos"),
    )


class ResourceCapabilityIndex(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "resource_capability_index"

    resource_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("resource_resource.entity_ulid", ondelete="CASCADE"),
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

    resource: Mapped[Resource] = relationship(
        "Resource", back_populates="capabilities"
    )

    __table_args__ = (
        UniqueConstraint(
            "resource_entity_ulid",
            "domain",
            "key",
            name="uq_res_cap_idx_triplet",
        ),
    )


class ResourcePOC(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "resource_poc"

    resource_entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("resource_resource.entity_ulid", ondelete="CASCADE"),
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

    resource: Mapped[Resource] = relationship(
        "Resource", back_populates="pocs"
    )

    __table_args__ = (
        UniqueConstraint(
            "resource_entity_ulid",
            "person_entity_ulid",
            "relation",
            "scope",
            name="uq_resource_poc_resource_person_scope",
        ),
        Index(
            "ix_resource_poc_org_scope_rank",
            "resource_entity_ulid",
            "relation",
            "scope",
            "rank",
        ),
        Index(
            "ix_resource_poc_primary",
            "resource_entity_ulid",
            "relation",
            "scope",
            "is_primary",
        ),
        CheckConstraint(
            "rank >= 0 AND rank <= 99", name="ck_resource_poc_rank_range"
        ),
    )


class ResourceAdminReviewRequest(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "resource_admin_review_request"

    entity_ulid: Mapped[str] = mapped_column(String(26), nullable=False)
    review_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # Example:
    # resource_onboard_review
    # resource_mou_status_review
    # resource_sla_status_review

    source_status: Mapped[str] = mapped_column(String(32), nullable=False)
    # pending_review | approved | rejected | cancelled

    requested_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    resolved_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    closed_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    __table_args__ = (
        db.Index(
            "ix_resource_admin_review_request_active",
            "entity_ulid",
            "review_kind",
            "source_status",
        ),
    )
