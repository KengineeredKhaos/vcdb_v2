# app/slices/entity/models.py
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
    person: Mapped["EntityPerson"] = relationship(
        "EntityPerson", back_populates="entity", uselist=False
    )
    org: Mapped["EntityOrg"] = relationship(
        "EntityOrg", back_populates="entity", uselist=False
    )

    # One-to-many
    roles: Mapped[list["EntityRole"]] = relationship(
        "EntityRole", back_populates="entity", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["EntityContact"]] = relationship(
        "EntityContact", back_populates="entity", cascade="all, delete-orphan"
    )
    addresses: Mapped[list["EntityAddress"]] = relationship(
        "EntityAddress", back_populates="entity", cascade="all, delete-orphan"
    )


# -------------------------
# Entity Person (1:1 with Entity)
# -------------------------
class EntityPerson(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "entity_person"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="person")

    first_name: Mapped[str] = mapped_column(String(40), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(
        String(60), nullable=True
    )

    archived_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # enforce 1:1 with Entity
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_person_entity"),
    )


# -------------------------
# Entity Organization (1:1 with Entity)
# -------------------------
class EntityOrg(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "entity_org"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="org")

    legal_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dba_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ein: Mapped[str | None] = mapped_column(
        String(9), nullable=True
    )  # normalized/validated in service

    archived_at: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # -------------
    # Relationships
    # -------------
    resource_pocs = relationship(
        "ResourcePOC",
        back_populates="org",
        cascade="all, delete-orphan",
        passive_deletes=True,  # honors ON DELETE CASCADE on FK
    )
    sponsor_pocs = relationship(
        "SponsorPOC",
        back_populates="org",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_org_entity"),  # enforce 1:1
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
