# app/slices/sponsors/models.py
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


class Sponsor(db.Model, ULIDPK):
    """
    A Sponsor is an org (EntityOrg) that provides cash, in-kind, or services.
    One Sponsor per Entity.
    """

    __tablename__ = "sponsor_sponsor"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity", index=True)
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_sponsor_entity"),
    )

    admin_review_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    readiness_status: Mapped[str] = mapped_column(
        String(16), default="draft", nullable=False, index=True
    )  # draft|review|active|suspended
    mou_status: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False, index=True
    )  # none|pending|active|expired|terminated

    first_seen_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_touch_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    capability_last_update_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    pledge_last_update_utc: Mapped[str | None] = mapped_column(
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

    histories: Mapped[list["SponsorHistory"]] = relationship(
        "SponsorHistory",
        back_populates="sponsor",
        cascade="all, delete-orphan",
    )
    capabilities: Mapped[list["SponsorCapabilityIndex"]] = relationship(
        "SponsorCapabilityIndex",
        back_populates="sponsor",
        cascade="all, delete-orphan",
    )
    pledges: Mapped[list["SponsorPledgeIndex"]] = relationship(
        "SponsorPledgeIndex",
        back_populates="sponsor",
        cascade="all, delete-orphan",
    )


class SponsorHistory(db.Model, ULIDPK):
    """
    Privacy A (strict). Stores snapshots for:
      - section='sponsor:capability:v1' : flattened "domain.key" -> {has:bool,note?:str}
      - section='sponsor:pledge:v1'     : {pledge_ulid:str -> pledge_payload}
    """

    __tablename__ = "sponsor_history"

    sponsor_ulid: Mapped[str] = ULIDFK("sponsor_sponsor", index=True)
    section: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_json: Mapped[str] = mapped_column(String, nullable=False)

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor", back_populates="histories"
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_sponsor_hist_version_pos"),
    )


class SponsorCapabilityIndex(db.Model, ULIDPK):
    """
    Projection for fast capability queries (names only, no notes).
    """

    __tablename__ = "sponsor_capability_index"

    sponsor_ulid: Mapped[str] = ULIDFK("sponsor_sponsor", index=True)
    domain: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
    )

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor", back_populates="capabilities"
    )

    __table_args__ = (
        UniqueConstraint(
            "sponsor_ulid", "domain", "key", name="uq_sponsor_cap_idx_triplet"
        ),
    )


class SponsorPledgeIndex(db.Model, ULIDPK):
    """
    Projection summary for pledges (no sensitive notes; minimal numbers for dashboards).
    """

    __tablename__ = "sponsor_pledge_index"

    sponsor_ulid: Mapped[str] = ULIDFK("sponsor_sponsor", index=True)
    pledge_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True, unique=True
    )

    type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # cash | in_kind
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # proposed|active|fulfilled|cancelled
    has_restriction: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    est_value_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # integer cents or units (MVP int)
    currency: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # USD etc.

    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
    )

    sponsor: Mapped["Sponsor"] = relationship(
        "Sponsor", back_populates="pledges"
    )
