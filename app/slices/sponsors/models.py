# app/slices/sponsors/models.py

"""
Sponsors slice — funding orgs, capability & pledge snapshots, allocations, POCs.

This module models organizations that act as Sponsors in VCDB v2: entities that
provide cash, in-kind support, or services under board-governed policies. Each
Sponsor is backed by a single EntityOrg record; this slice never stores PII,
only ULIDs and policy-/reporting-friendly attributes.

Models:

* Sponsor
    One row per sponsoring org, keyed by `entity_ulid` from EntityOrg
    (enforced 1:1 via uq_sponsor_entity). Tracks governance-facing lifecycle
    state: admin_review_required, readiness_status, mou_status, and a handful
    of ISO8601 timestamps (first_seen, last_touch, capability_last_update,
    pledge_last_update). This is the anchor record for all sponsor-related
    capabilities, pledges, allocations, and POCs.

* SponsorHistory
    Privacy A (strict) snapshot store for sponsor-level details. Sections:
      - 'sponsor:capability:v1': flattened "domain.key" -> {has: bool, note?: str}
      - 'sponsor:pledge:v1'    : {pledge_ulid: payload}
    Designed for governance/admin UIs and audits; contents should not be
    indexed or leaked to logs or ledger. A CHECK constraint enforces a
    positive version number.

* SponsorCapabilityIndex
    Projection table for fast, names-only capability queries. Each row is a
    (sponsor_ulid, domain, key, active) triplet with a UNIQUE constraint, built
    from SponsorHistory. This lets other slices answer questions like "which
    sponsors fund housing?" without touching sensitive notes.

* SponsorPledgeIndex
    Projection summary for pledges, keyed by pledge_ulid. Stores only
    high-level type (cash/in_kind), status (proposed/active/fulfilled/
    cancelled), whether a restriction exists, and a coarse numeric estimate
    (est_value_number + currency). Detailed pledge terms/notes live in
    SponsorHistory or external documents, not here.

* Allocation
    Sponsor allocation to a Customer, PII-free. Links a sponsor_ulid to a
    customer_ulid and records the authorized amount (integer cents), state
    (e.g. committed), an optional approver ULID, and an optional ISO8601
    expiry date. Governance policy and Finance integrate here: Governance
    enforces who may approve and under what conditions; Finance records the
    monetary impact in the journal. A CHECK constraint enforces non-negative
    amounts.

* SponsorPOC
    Slice-owned linkage between a Sponsor and one or more people (EntityPerson)
    serving as points-of-contact for an EntityOrg. Stores only ULIDs plus
    Governance-governed metadata: relation, scope, rank, org_role, validity
    windows, is_primary, and active. Uniqueness and indexed ordering over
    (sponsor_ulid, relation, scope, rank/is_primary) support "who do we call?"
    lookups without duplicating names, emails, or phone numbers.

Ownership and boundaries:

* The Sponsors slice owns these tables and is responsible for keeping PII in
  the Entity slice and detailed pledge/capability data in SponsorHistory.
  Other slices must interact via services/contracts using ULIDs and normalized
  keys, not by importing these models directly.
* Governance defines sponsor capability taxonomies, pledge and allocation
  policies, MOU semantics, and who can approve allocations; Sponsors applies
  that policy when updating histories, indexes, and Allocation rows.
* Finance is responsible for recording the monetary side of pledges and
  allocations in the journal; Sponsors stores only structured references and
  high-level numbers.
* Ledger and logging must continue to record only ULIDs and normalized labels;
  any narrative or sensitive notes live in snapshot JSON or external systems,
  not in logs or the ledger.

In short, this module provides the structural backbone for "who funds what, on
what terms, and to which customers" while keeping identity and detailed pledge
terms in the appropriate slices.
"""

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
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


class Sponsor(db.Model, ULIDPK, IsoTimestamps):
    """
    A Sponsor is an org (EntityOrg) that provides cash, in-kind, or services.
    One Sponsor per Entity.
    """

    __tablename__ = "sponsor_sponsor"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity", index=True)
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_sponsor_entity"),
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


class SponsorHistory(db.Model, ULIDPK, IsoTimestamps):
    """
    Privacy A (strict). Stores snapshots for:
      - section='sponsor:capability:v1' : flattened "domain.key" -> {has:bool,note?:str}
      - section='sponsor:pledge:v1'     : {pledge_ulid:str -> pledge_payload}
    """

    __tablename__ = "sponsor_history"

    sponsor_ulid: Mapped[str] = ULIDFK("sponsor_sponsor", index=True)
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

    sponsor_ulid: Mapped[str] = ULIDFK("sponsor_sponsor", index=True)
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
            "sponsor_ulid", "domain", "key", name="uq_sponsor_cap_idx_triplet"
        ),
    )


class SponsorPledgeIndex(db.Model, ULIDPK, IsoTimestamps):
    """
    Projection summary for pledges (no sensitive notes; minimal numbers for dashboards).
    """

    __tablename__ = "sponsor_pledge_index"

    sponsor_ulid: Mapped[str] = ULIDFK("sponsor_sponsor", index=True)
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


class Allocation(db.Model, ULIDPK, IsoTimestamps):
    """
    Sponsor allocation to a Customer.
    PII-free. ISO-8601 Z string timestamps via IsoTimestamps.
    """

    __tablename__ = "sponsor_allocation"

    sponsor_ulid: Mapped[str] = ULIDFK(
        "sponsor_sponsor", index=True, nullable=False
    )
    customer_ulid: Mapped[str] = ULIDFK(
        "entity_entity", index=True, nullable=False
    )

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="committed", index=True
    )
    # cents, non-negative
    amount_authorized_cents: Mapped[int] = mapped_column(
        nullable=False, default=0
    )
    approved_by_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    # keep expiry as ISO string to stay consistent with the rest of the slice
    expires_on_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # relationships (optional, for convenience)
    sponsor = relationship("Sponsor", backref="allocations")

    __table_args__ = (
        CheckConstraint(
            "amount_authorized_cents >= 0", name="ck_alloc_amount_nonneg"
        ),
    )


class SponsorPOC(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "sponsor_poc"

    sponsor_ulid: Mapped[str] = ULIDFK(
        "sponsor_sponsor", ondelete="CASCADE", nullable=False, index=True
    )
    person_entity_ulid: Mapped[str] = ULIDFK(
        "entity_person", ondelete="RESTRICT", nullable=False, index=True
    )

    relation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="poc"
    )

    org_entity_ulid: Mapped[str] = ULIDFK(
        "entity_org", ondelete="CASCADE", nullable=False, index=True
    )

    org_entity_ulid: Mapped[str] = ULIDFK(
        "entity_org", ondelete="CASCADE", nullable=False, index=True
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

    org: Mapped["EntityOrg"] = relationship(
        "EntityOrg",
        back_populates="sponsor_pocs",
        passive_deletes=True,
    )
    person: Mapped["EntityPerson"] = relationship(
        "EntityPerson",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "sponsor_ulid",
            "person_entity_ulid",
            "relation",
            "scope",
            name="uq_sponsor_poc_sponsor_person_scope",
        ),
        Index(
            "ix_sponsor_poc_org_scope_rank",
            "sponsor_ulid",
            "relation",
            "scope",
            "rank",
        ),
        Index(
            "ix_sponsor_poc_primary",
            "sponsor_ulid",
            "relation",
            "scope",
            "is_primary",
        ),
        CheckConstraint(
            "rank >= 0 AND rank <= 99", name="ck_sponsor_poc_rank_range"
        ),
    )
