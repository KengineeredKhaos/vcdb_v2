# app/slices/entity/models.py

"""
Entity slice — canonical people/org registry and their basic contact surface.

This module defines the core "Entity" model for VCDB v2 and its immediate
one-to-one / one-to-many satellites. Every person or organization known to
the system gets a single Entity row; all other slices reference that identity
via `entity_ulid` instead of storing their own PII.

Models:

* Entity
    Root record keyed by ULID, with a simple `kind` ("person", "org", etc.)
    and timestamp metadata. It owns the 1:1 relationships to EntityPerson and
    EntityOrg, plus 1:N relationships to roles, contacts, and addresses. This
    is the canonical ID other slices use as `entity_ulid`.
* EntityPerson
    1:1 extension of Entity for people. Stores first/last name and an optional
    preferred name. Enforced as a strict 1:1 via a UNIQUE constraint on
    `entity_ulid`. All name normalization and validation happens in services.
* EntityOrg
    1:1 extension of Entity for organizations. Stores legal_name, optional DBA,
    and an optional EIN. Enforced as a strict 1:1 via a UNIQUE constraint on
    `entity_ulid` and a separate UNIQUE constraint on EIN (subject to DB
    behavior with NULLs). It also owns backrefs to ResourcePOC/SponsorPOC so
    Resource/Sponsor slices can attach POCs without duplicating org identity.
* EntityRole
    1:N roles attached to an Entity (e.g., "customer", "staff", "governor").
    Governance defines which role strings are valid; the DB enforces uniqueness
    per entity via (entity_ulid, role). These are "system roles", distinct from
    Auth RBAC roles, and are safe to expose via contracts (no PII).
* EntityContact
    1:N contact methods per Entity (email/phone, plus a primary flag). Values
    are normalized and validated in services, not here. Useful for quick
    lookups and UI display; other slices should not duplicate email/phone.
* EntityAddress
    1:N addresses per Entity. Distinguishes physical vs postal (either/both)
    and stores normalized address fields, including a two-letter state code
    enforced by a CHECK constraint. All higher-level geo policy (allowed
    states, service areas) lives in Governance.

Ownership and boundaries:

* The Entity slice is the single source of truth for people/org identity,
  contacts, and addresses. No other slice should store names, emails, phones,
  or raw addresses; they should reference `entity_ulid` instead.
* Other slices (Customers, Resources, Sponsors, Auth, etc.) may attach their
  own records to an Entity via foreign keys but must not reach into these
  tables directly; they should go through services/contracts where possible.
* Ledger and logging must never store PII from these models; they refer only to
  ULIDs and non-identifying role labels.

In short, this module gives VCDB v2 a unified identity spine for all people and
organizations, with a clean separation between core identity data here and
slice-specific behavior elsewhere.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


# -------------------------
# Core "Entity"
# -------------------------
class Entity(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "entity_entity"

    # PK 'ulid' comes from ULIDPK (String(26), default=new_ulid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    archived_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # One-to-ones
    person: Mapped[EntityPerson] = relationship(
        "EntityPerson", back_populates="entity", uselist=False
    )
    org: Mapped[EntityOrg] = relationship(
        "EntityOrg", back_populates="entity", uselist=False
    )

    # One-to-many
    roles: Mapped[list[EntityRole]] = relationship(
        "EntityRole", back_populates="entity", cascade="all, delete-orphan"
    )
    contacts: Mapped[list[EntityContact]] = relationship(
        "EntityContact", back_populates="entity", cascade="all, delete-orphan"
    )
    addresses: Mapped[list[EntityAddress]] = relationship(
        "EntityAddress", back_populates="entity", cascade="all, delete-orphan"
    )


# -------------------------
# Entity Person (1:1 with Entity)
# -------------------------
class EntityPerson(db.Model, IsoTimestamps):
    """
    FACET TABLE (anchor = entity_ulid):
    Primary key is entity_ulid (same ULID as the Entity row).
    """

    __tablename__ = "entity_person"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("entity_entity.ulid", ondelete="CASCADE"),
        primary_key=True,
    )
    entity: Mapped[Entity] = relationship("Entity", back_populates="person")

    first_name: Mapped[str] = mapped_column(String(40), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(
        String(60), nullable=True
    )
    last_4: Mapped[str] = mapped_column(String(4), nullable=True)
    dob: Mapped[str] = mapped_column(String(10), nullable=True)


# -------------------------
# Entity Organization (1:1 with Entity)
# -------------------------
class EntityOrg(db.Model, IsoTimestamps):
    """
    FACET TABLE (anchor = entity_ulid):
    Primary key is entity_ulid (same ULID as the Entity row).
    """

    __tablename__ = "entity_org"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        db.ForeignKey("entity_entity.ulid", ondelete="CASCADE"),
        primary_key=True,
    )
    entity: Mapped[Entity] = relationship("Entity", back_populates="org")

    legal_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dba_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ein: Mapped[str | None] = mapped_column(
        String(9), nullable=True
    )  # normalized/validated in service

    __table_args__ = (
        UniqueConstraint("ein", name="uq_org_ein"),
        # works ONLY if DB allows UNIQUE with NULLs
    )


# -------------------------
# Entity Role (N:1 with Entity)
# -------------------------
class EntityRole(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "entity_role"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="roles")

    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    archived_at: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        # Governance enforces allowed values;
        # DB enforces uniqueness per entity
        UniqueConstraint("entity_ulid", "role", name="uq_entity_role_pair"),
    )


# -------------------------
# Entity Contact (N:1 with Entity)
# -------------------------
class EntityContact(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "entity_contact"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="contacts")

    email: Mapped[str | None] = mapped_column(
        String(254), nullable=True
    )  # normalized/validated in service
    phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # normalized/validated in service
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    archived_at: Mapped[str | None] = mapped_column(String(30), nullable=True)


# -------------------------
# Entity Address (N:1 with Entity)
# -------------------------
class EntityAddress(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "entity_address"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship(
        "Entity", back_populates="addresses"
    )

    is_physical: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_postal: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    address1: Mapped[str] = mapped_column(String(80), nullable=False)
    address2: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[str] = mapped_column(
        String(2), nullable=False
    )  # two-letter code; validate in service
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        CheckConstraint("length(state) = 2", name="ck_state_len_2"),
    )


__all__ = [
    "Entity",
    "EntityPerson",
    "EntityOrg",
    "EntityRole",
    "EntityContact",
    "EntityAddress",
]
