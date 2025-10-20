# app/slices/customers/models.py
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.chrono import now_iso8601_ms, utcnow_naive
from app.lib.models import ULIDFK, ULIDPK


class Customer(db.Model, ULIDPK):
    __tablename__ = "customer_customer"

    # one Customer per Entity
    entity_ulid: Mapped[str] = ULIDFK("entity_entity", index=True)
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_customer_entity"),
    )

    # derived cues (denormalized for dashboards/lists)
    tier1_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    tier2_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    tier3_min: Mapped[int | None] = mapped_column(Integer, nullable=True)

    flag_tier1_immediate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    watchlist: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # lifecycle/status
    status: Mapped[str] = mapped_column(
        String(24), default="active", nullable=False, index=True
    )

    # ops timestamps (denormalized; for fast UI)
    first_seen_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_touch_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # needs tracking helpers
    last_needs_update_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_needs_tier_updated: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # "tier1"|"tier2"|"tier3"
    flag_reason: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )  # e.g. "food=1"
    watchlist_since_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
    )

    histories: Mapped[list["CustomerHistory"]] = relationship(
        "CustomerHistory",
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class CustomerHistory(db.Model, ULIDPK):
    """
    Privacy A (strict): stores sensitive snapshots. Values live ONLY here.
    """

    __tablename__ = "customer_history"

    customer_ulid: Mapped[str] = ULIDFK("customer_customer", index=True)
    section: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # 'profile:needs:tier1'|tier2|tier3
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    data_json: Mapped[str] = mapped_column(String, nullable=False)

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="histories"
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_history_version_pos"),
    )
