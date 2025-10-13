# app/slices/auth/models.py
from __future__ import annotations

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.chrono import utc_now
from app.lib.models import ULIDFK, ULIDPK


class User(db.Model, ULIDPK):
    __tablename__ = "auth_user"

    # Optional link to the person/org "Entity" record (no cross-slice import)
    entity_ulid: Mapped[str | None] = ULIDFK(
        "entity_entity", nullable=True, index=True
    )

    username: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True
    )
    email: Mapped[str | None] = mapped_column(
        String(254), nullable=True, unique=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utc_now, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utc_now, onupdate=utc_now, nullable=False
    )
    last_login_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    roles = relationship(
        "Role", secondary="auth_user_role", back_populates="users"
    )


class Role(db.Model, ULIDPK):
    __tablename__ = "auth_role"

    # RBAC role codes (keep small + fixed: 'user', 'auditor', 'admin')
    code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )

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
    )
