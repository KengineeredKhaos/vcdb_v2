# app/slices/governance/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.chrono import now_iso8601_ms, utcnow_naive
from app.lib.models import ULIDPK


class CanonicalState(db.Model, ULIDPK):
    __tablename__ = "gov_canonical_state"
    code: Mapped[str] = mapped_column(String(2), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=utcnow_naive
    )
    updated_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive
    )


class ServiceClassification(db.Model, ULIDPK):
    __tablename__ = "gov_service_class"
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128))
    sort: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=utcnow_naive
    )
    updated_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive
    )
    __table_args__ = (Index("ix_gov_service_class_sort", "sort"),)


class RoleCode(db.Model, ULIDPK):
    """
    Canonical list of allowed RBAC role codes (read-only for other slices).
    Auth slice still owns actual assignments; this just publishes the vocabulary.
    """

    __tablename__ = "gov_role_code"
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=utcnow_naive
    )
    updated_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive
    )


class Policy(db.Model, ULIDPK):
    """
    Versioned governance policies.
    NOTE: timestamps are stored as ISO-8601 strings
    to match existing migrations.
    """

    __tablename__ = "governance_policy"

    namespace: Mapped[str] = mapped_column(String(40), index=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # JSON blobs (use String/Text; SQLite doesn’t enforce size)
    value_json: Mapped[str] = mapped_column(String)
    schema_json: Mapped[str] = mapped_column(String, default="")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Actor who last updated (ULID) – optional
    updated_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # Store as ISO-8601 strings (VARCHAR(30)) to match your migration history
    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, onupdate=now_iso8601_ms
    )

    __table_args__ = (
        UniqueConstraint(
            "namespace", "key", "version", name="uq_governance_policy_version"
        ),
        Index("ix_governance_policy_active", "namespace", "key", "is_active"),
    )
