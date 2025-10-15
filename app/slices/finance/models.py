# app/slices/finance/models.py
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
from app.lib.chrono import now_iso8601_ms
from app.lib.models import ULIDPK

# ---- Reference tables ------------------------------------------------------


class Account(db.Model, ULIDPK):
    __tablename__ = "finance_account"

    code: Mapped[str] = mapped_column(
        String(24), unique=True, index=True, nullable=False
    )  # e.g., "1000", "4100"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # asset|liability|net_assets|revenue|expense
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )


class Fund(db.Model, ULIDPK):
    __tablename__ = "finance_fund"

    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )  # e.g., "unrestricted", "TEMP-GRANT25"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    restriction: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # unrestricted|temp|perm
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )


class Project(db.Model, ULIDPK):
    __tablename__ = "finance_project"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )


class Period(db.Model, ULIDPK):
    __tablename__ = "finance_period"

    period_key: Mapped[str] = mapped_column(
        String(7), unique=True, index=True, nullable=False
    )  # YYYY-MM
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="open"
    )  # open|soft_closed|closed

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )


# ---- Journals --------------------------------------------------------------


class Journal(db.Model, ULIDPK):
    __tablename__ = "finance_journal"

    source: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # e.g., sponsors|resources|logistics
    external_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="USD"
    )
    period_key: Mapped[str] = mapped_column(
        String(7), nullable=False, index=True
    )  # YYYY-MM
    happened_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    posted_at_utc: Mapped[str] = mapped_column(
        String(30), nullable=False, default=utcnow_naive
    )

    memo: Mapped[str | None] = mapped_column(String(160), nullable=True)

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )

    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine", back_populates="journal", cascade="all, delete-orphan"
    )


class JournalLine(db.Model, ULIDPK):
    __tablename__ = "finance_journal_line"

    journal_ulid: Mapped[str] = mapped_column(
        String(26), index=True, nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    account_code: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True
    )
    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # +debit / -credit
    memo: Mapped[str | None] = mapped_column(String(160), nullable=True)

    period_key: Mapped[str] = mapped_column(
        String(7), nullable=False, index=True
    )  # duplicate for fast rollups

    journal: Mapped["Journal"] = relationship(
        "Journal", back_populates="lines"
    )

    __table_args__ = (
        CheckConstraint("amount_cents != 0", name="ck_line_nonzero"),
    )


# ---- Balances Projection (rebuildable) -------------------------------------


class BalanceMonthly(db.Model, ULIDPK):
    __tablename__ = "finance_balance_monthly"

    account_code: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True
    )
    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    period_key: Mapped[str] = mapped_column(
        String(7), nullable=False, index=True
    )

    debits_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    credits_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    net_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    updated_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "account_code",
            "fund_code",
            "project_ulid",
            "period_key",
            name="uq_balance_key",
        ),
    )


# ---- Optional: Statistical metrics (non-monetary) --------------------------


class StatMetric(db.Model, ULIDPK):
    __tablename__ = "finance_stat_metric"

    period_key: Mapped[str] = mapped_column(
        String(7), nullable=False, index=True
    )
    metric_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # e.g., STAT_FOOD_LBS
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # integers only
    unit: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # lbs|kits|each
    source: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # logistics|resources
    source_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=utcnow_naive, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "period_key",
            "metric_code",
            "source",
            "source_ref_ulid",
            name="uq_stat_dedupe",
        ),
    )
