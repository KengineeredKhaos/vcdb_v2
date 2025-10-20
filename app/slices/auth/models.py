# app/slices/auth/models.py
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
from app.lib.chrono import now_iso8601_ms
from app.lib.models import ULIDFK, ULIDPK


class User(db.Model, ULIDPK):
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

    created_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    updated_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
    )

    # relationship via association table
    roles = relationship(
        "Role",
        secondary="auth_user_role",
        back_populates="users",
        lazy="joined",
    )


class Role(db.Model, ULIDPK):
    __tablename__ = "auth_role"

    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True
    )  # e.g., "user", "auditor", "admin"
    description: Mapped[str | None] = mapped_column(String(200), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    updated_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
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
        Index("ix_auth_user_role_user", "user_ulid"),
        Index("ix_auth_user_role_role", "role_ulid"),
    )
