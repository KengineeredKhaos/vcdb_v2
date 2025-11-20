# app/slices/resources/models.py
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


class Resource(db.Model, ULIDPK, IsoTimestamps):
    """
    A Resource is a service-providing organization (backed by EntityOrg).
    One Resource row per Entity (entity_ulid).
    """

    __tablename__ = "resource_resource"

    # DB-level FK to entity slice (no cross-slice service import)
    entity_ulid: Mapped[str] = ULIDFK("entity_entity", index=True)
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_resource_entity"),
    )

    # Operational flags / lifecycle (no PII)
    admin_review_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    readiness_status: Mapped[str] = mapped_column(
        String(16), default="draft", nullable=False, index=True
    )  # draft|review|active|suspended
    mou_status: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False, index=True
    )  # none|pending|active|expired|terminated

    # Ops timestamps
    first_seen_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_touch_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    capability_last_update_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # -------------
    # Relationships
    # -------------

    histories: Mapped[list["ResourceHistory"]] = relationship(
        "ResourceHistory",
        back_populates="resource",
        cascade="all, delete-orphan",
    )
    capabilities: Mapped[list["ResourceCapabilityIndex"]] = relationship(
        "ResourceCapabilityIndex",
        back_populates="resource",
        cascade="all, delete-orphan",
    )
    pocs: Mapped[list["ResourcePOC"]] = relationship(
        "ResourcePOC",
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ResourceHistory(db.Model, ULIDPK, IsoTimestamps):
    """
    Privacy A (strict): capability snapshot values (booleans & notes)
    live ONLY here. Section fixed to 'resource:capability:v1' for now.
    """

    __tablename__ = "resource_history"

    resource_ulid: Mapped[str] = ULIDFK("resource_resource", index=True)
    section: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # 'resource:capability:v1'
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_json: Mapped[str] = mapped_column(
        String, nullable=False
    )  # flattened key -> {has: bool, note?: str}

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    resource: Mapped["Resource"] = relationship(
        "Resource", back_populates="histories"
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_res_history_version_pos"),
    )


class ResourceCapabilityIndex(db.Model, ULIDPK, IsoTimestamps):
    """
    Materialized 'current state' index for fast search/filter.
    Names only; NO NOTES here. Rebuilt on each capability upsert.
    """

    __tablename__ = "resource_capability_index"

    resource_ulid: Mapped[str] = ULIDFK("resource_resource", index=True)
    domain: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    resource: Mapped["Resource"] = relationship(
        "Resource", back_populates="capabilities"
    )

    __table_args__ = (
        UniqueConstraint(
            "resource_ulid", "domain", "key", name="uq_res_cap_idx_triplet"
        ),
    )


class ResourcePOC(db.Model, ULIDPK, IsoTimestamps):
    """
    Slice-owned linkage row connecting a Resource org to a Person entity as a POC,
    with Governance-constrained metadata (scope, rank, etc.). No PII here.
    """

    __tablename__ = "resource_poc"

    resource_ulid: Mapped[str] = ULIDFK(
        "resource_resource", ondelete="CASCADE", nullable=False, index=True
    )
    # Person ULID from Entity slice
    person_entity_ulid: Mapped[str] = ULIDFK(
        "entity_person", ondelete="RESTRICT", nullable=False, index=True
    )

    # Optional relation label (keep "poc" as default in services if you like)
    relation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="poc"
    )

    org_entity_ulid: Mapped[str] = ULIDFK(
        "entity_org", ondelete="CASCADE", nullable=False, index=True
    )

    # Governance-constrained
    scope: Mapped[str] = mapped_column(
        String(24), nullable=True
    )  # validated in service
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Freeform org-visible title/descriptor
    org_role: Mapped[str] = mapped_column(String(64), nullable=True)

    # Window as ISO-8601 strings (match your IsoTimestamps format)
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

    resource: Mapped["Resource"] = relationship(
        "Resource",
        back_populates="pocs",
    )

    org: Mapped["EntityOrg"] = relationship(
        "EntityOrg",
        back_populates="resource_pocs",
        foreign_keys="ResourcePOC.org_entity_ulid",
        passive_deletes=True,
    )
    person: Mapped["EntityPerson"] = relationship(
        "EntityPerson",
        passive_deletes=True,
    )

    __table_args__ = (
        # Uniqueness allows same person to serve multiple scopes if needed
        UniqueConstraint(
            "resource_ulid",
            "person_entity_ulid",
            "relation",
            "scope",
            name="uq_resource_poc_resource_person_scope",
        ),
        # Helpful ordering / primary lookups
        Index(
            "ix_resource_poc_org_scope_rank",
            "resource_ulid",
            "relation",
            "scope",
            "rank",
        ),
        Index(
            "ix_resource_poc_primary",
            "resource_ulid",
            "relation",
            "scope",
            "is_primary",
        ),
        CheckConstraint(
            "rank >= 0 AND rank <= 99", name="ck_resource_poc_rank_range"
        ),
    )
