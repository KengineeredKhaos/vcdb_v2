# app/slices/governance/models.py
from __future__ import annotations

from sqlalchemy import String, Boolean, Integer, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import ULIDPK, ULIDFK
from app.lib.chrono import utc_now


class Policy(db.Model, ULIDPK):
    """
    Versioned policy document; one active version per (namespace, key).
    """

    __tablename__ = "governance_policy"

    namespace: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # e.g. "governance"
    key: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # e.g. "roles"
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Store JSON as TEXT in SQLite; keep shape at the service boundary.
    value_json: Mapped[str] = mapped_column(
        String, nullable=False
    )  # stable_dumps(value)
    schema_json: Mapped[str | None] = mapped_column(String, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    updated_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utc_now, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "namespace", "key", "is_active", name="uq_policy_active_one"
        ),
        Index("ix_policy_family", "namespace", "key", "is_active"),
    )


class CapabilityGrant(db.Model, ULIDPK):
    """
    Grants a named capability to a principal (an Entity) in an optional scope.
    Keep this distinct from RBAC (Auth slice); this is domain capability.
    """

    __tablename__ = "governance_capability_grant"

    principal_ulid: Mapped[str] = ULIDFK(
        "entity_entity", index=True
    )  # ← matches your Entity table
    capability: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )  # e.g., "governor"
    scope: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # freeform "finance:*" or JSON pointer

    issued_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    expires_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utc_now, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utc_now, onupdate=utc_now, nullable=False
    )
