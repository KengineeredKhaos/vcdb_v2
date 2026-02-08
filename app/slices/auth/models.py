# app/slices/auth/models.py

"""

VCDB v2 — Auth slice models

This module defines the **RBAC user account tables** for VCDB v2.
Auth owns authentication and RBAC role membership only. It does **not**
own domain roles (customer/resource/sponsor/governor); those are governed
by the Governance slice and exposed via contracts.

Tables
======

User
    Core authentication identity for a human user of the system.
    - Primary key is a ULID (see app/lib/ids.py).
    - Carries login fields (username, email, password_hash) and flags
      for active/locked accounts.
    - Timestamp mixin (IsoTimestamps) tracks created/updated times.

Role
    RBAC role catalog for auth-level permissions.
    - Examples: "user", "staff", "admin", "auditor", "dev".
    - Role codes are defined by Auth RBAC policy;
    - Governance defines cross-slice rules (RBAC↔domain constraints).

UserRole
    Many-to-many join table linking Users to Roles.
    - Each (user_id, role_id) pair is unique.
    - Represents the current RBAC permissions granted to a user.

Ownership and boundaries
========================

* Auth is the **single owner** of the User/Role/UserRole tables and any
  SQL touching them.
* Other slices must not query these tables directly; they interact with
  Auth via contracts and helpers in app/lib/security.py.
* Domain roles (customer/resource/sponsor/governor, officer roles, etc.)
  live in Governance and are *not* stored here.

Ledger
======

Auth services (create_user, set_account_roles, etc.) are responsible for
emitting ledger events (via the event_bus and ledger_v2 contract) when
auth-relevant facts change. This keeps all authentication-related side
effects inside the Auth slice while still giving the rest of the system
a consistent audit trail.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


class User(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "auth_user"

    entity_ulid: Mapped[str | None] = mapped_column(
        String(26), index=True, nullable=True
    )

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)

    last_login_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # relationship via association table
    roles = relationship(
        "Role",
        secondary="auth_user_role",
        back_populates="users",
        lazy="joined",
    )


class Role(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "auth_role"

    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True
    )  # e.g., "user", "auditor", "admin"
    description: Mapped[str | None] = mapped_column(String(200), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users = relationship(
        "User", secondary="auth_user_role", back_populates="roles"
    )


class UserRole(db.Model, ULIDPK):
    __tablename__ = "auth_user_role"
    user_ulid: Mapped[str] = ULIDFK("auth_user")
    role_ulid: Mapped[str] = ULIDFK("auth_role")

    __table_args__ = (
        UniqueConstraint(
            "user_ulid", "role_ulid", name="uq_auth_user_role_pair"
        ),
        Index("ix_auth_user_role_user", "user_ulid"),
        Index("ix_auth_user_role_role", "role_ulid"),
    )
