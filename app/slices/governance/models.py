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
from app.lib.chrono import utcnow_naive
from app.lib.models import ULIDPK


class CanonicalState(db.Model, ULIDPK):
    __tablename__ = "gov_canonical_state"
    code: Mapped[str] = mapped_column(String(2), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive
    )


class ServiceClassification(db.Model, ULIDPK):
    __tablename__ = "gov_service_class"
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128))
    sort: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive
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
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive
    )
