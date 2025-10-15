# app/slices/entity/models.py
from __future__ import annotations

from sqlalchemy import String, UniqueConstraint, CheckConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.chrono import now_iso8601_ms, utcnow_naive
from app.lib.models import ULIDPK, ULIDFK


# -------------------------
# Core "Entity"
# -------------------------
class Entity(db.Model, ULIDPK):
    __tablename__ = "entity_entity"

    # PK 'ulid' comes from ULIDPK (String(26), default=new_ulid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=utcnow_naive,
        onupdate=utcnow_naive,
        nullable=False,
    )

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
class EntityPerson(db.Model, ULIDPK):
    __tablename__ = "entity_person"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="person")

    first_name: Mapped[str] = mapped_column(String(40), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(
        String(60), nullable=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=utcnow_naive,
        onupdate=utcnow_naive,
        nullable=False,
    )

    # enforce 1:1 with Entity
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_person_entity"),
    )


# -------------------------
# Entity Organization (1:1 with Entity)
# -------------------------
class EntityOrg(db.Model, ULIDPK):
    __tablename__ = "entity_org"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="org")

    legal_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dba_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ein: Mapped[str | None] = mapped_column(
        String(9), nullable=True
    )  # normalized/validated in service

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=utcnow_naive,
        onupdate=utcnow_naive,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_org_entity"),  # enforce 1:1
    )


# -------------------------
# Entity Role (N:1 with Entity)
# -------------------------
class EntityRole(db.Model, ULIDPK):
    __tablename__ = "entity_role"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="roles")

    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=utcnow_naive,
        onupdate=utcnow_naive,
        nullable=False,
    )

    __table_args__ = (
        # Governance enforces allowed values;
        # DB enforces uniqueness per entity
        UniqueConstraint("entity_ulid", "role", name="uq_entity_role_pair"),
    )


# -------------------------
# Entity Contact (N:1 with Entity)
# -------------------------
class EntityContact(db.Model, ULIDPK):
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

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=utcnow_naive,
        onupdate=utcnow_naive,
        nullable=False,
    )


# -------------------------
# Entity Address (N:1 with Entity)
# -------------------------
class EntityAddress(db.Model, ULIDPK):
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

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=utcnow_naive,
        onupdate=utcnow_naive,
        nullable=False,
    )

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
