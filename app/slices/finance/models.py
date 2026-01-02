# app/slices/finance/models.py
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.models import ULIDPK, IsoTimestamps

# -----------------
# Reference tables
# -----------------


class Account(db.Model, ULIDPK, IsoTimestamps):
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

    __table_args__ = (
        CheckConstraint(
            "type in ('asset','liability','net_assets','revenue','expense')",
            name="ck_account_type",
        ),
    )


class Fund(db.Model, ULIDPK, IsoTimestamps):
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

    __table_args__ = (
        CheckConstraint(
            "restriction in ('unrestricted','temp','perm')",
            name="ck_fund_restriction",
        ),
    )


class FinanceProject(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_project"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )


class Period(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_period"

    period_key: Mapped[str] = mapped_column(
        String(7), unique=True, index=True, nullable=False
    )  # YYYY-MM
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="open"
    )  # open|soft_closed|closed

    __table_args__ = (
        CheckConstraint(
            "status in ('open','soft_closed','closed')",
            name="ck_period_status",
        ),
    )


# -----------------
# Journal
# -----------------


class Journal(db.Model, ULIDPK, IsoTimestamps):
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
        String(30), nullable=False, default=now_iso8601_ms
    )

    memo: Mapped[str | None] = mapped_column(String(160), nullable=True)

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine",
        back_populates="journal",
        cascade="all, delete-orphan",
        order_by="JournalLine.seq",
    )


# -----------------
# JournalLine
# -----------------


class JournalLine(db.Model, ULIDPK):
    __tablename__ = "finance_journal_line"

    journal_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_journal.ulid"),
        index=True,
        nullable=False,
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
        UniqueConstraint("journal_ulid", "seq", name="uq_journalline_seq"),
    )


# -----------------
# Balances Projection
# (rebuildable)
# -----------------


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

    __table_args__ = (
        UniqueConstraint(
            "account_code",
            "fund_code",
            "project_ulid",
            "period_key",
            name="uq_balance_key",
        ),
    )


# -----------------
# Optional:
# Statistical metrics
# (non-monetary)
# -----------------


class StatMetric(db.Model, ULIDPK, IsoTimestamps):
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

    __table_args__ = (
        UniqueConstraint(
            "period_key",
            "metric_code",
            "source",
            "source_ref_ulid",
            name="uq_stat_dedupe",
        ),
    )


# -----------------
# Grants &
# Reimbursements
# -----------------


class Grant(db.Model, ULIDPK, IsoTimestamps):
    """
    Finance representation of a grant commitment from a sponsor.

    This is a *program* or *award* level object:

        - which fund the grant flows through
        - which sponsor it comes from
        - total award amount and match requirement
        - term dates
        - reporting cadence
        - which expense categories are allowable

    Journal entries still live in Journal / JournalLine; this table
    only stores the “paperwork” and configuration for that grant.
    """

    __tablename__ = "finance_grant"

    fund_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_fund.ulid"),
        nullable=False,
        index=True,
    )
    sponsor_ulid: Mapped[str] = mapped_column(
        String(26),
        nullable=False,
        index=True,
    )

    amount_awarded_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    match_required_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # YYYY-MM-DD strings, consistent with other date-ish string fields
    start_on: Mapped[str] = mapped_column(String(10), nullable=False)
    end_on: Mapped[str] = mapped_column(String(10), nullable=False)

    reporting_frequency: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # monthly|quarterly|semiannual|annual|end_of_term

    # Stored as a comma-separated list, with helpers for a Python list
    allowable_categories_raw: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )

    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "reporting_frequency in "
            "('monthly','quarterly','semiannual','annual','end_of_term')",
            name="ck_grant_reporting_frequency",
        ),
    )

    reimbursements: Mapped[list["Reimbursement"]] = relationship(
        "Reimbursement",
        back_populates="grant",
        cascade="all, delete-orphan",
        order_by="Reimbursement.submitted_on",
    )

    @property
    def allowable_categories(self) -> list[str]:
        if not self.allowable_categories_raw:
            return []
        return [c for c in self.allowable_categories_raw.split(",") if c]

    @allowable_categories.setter
    def allowable_categories(self, categories: list[str]) -> None:
        cleaned = sorted(
            {c.strip() for c in categories or [] if c and c.strip()}
        )
        self.allowable_categories_raw = ",".join(cleaned)


class Reimbursement(db.Model, ULIDPK, IsoTimestamps):
    """
    A reimbursement request submitted against a Grant.

    This is *paperwork level*:

        - which grant
        - what period it covers
        - how much we’re asking for
        - current status in the reimbursement workflow
    """

    __tablename__ = "finance_reimbursement"

    grant_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_grant.ulid"),
        nullable=False,
        index=True,
    )

    submitted_on: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # YYYY-MM-DD
    period_start: Mapped[str] = mapped_column(String(10), nullable=False)
    period_end: Mapped[str] = mapped_column(String(10), nullable=False)

    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="submitted", index=True
    )  # draft|submitted|approved|paid|void

    __table_args__ = (
        CheckConstraint(
            "status in ('draft','submitted','approved','paid','void')",
            name="ck_reimbursement_status",
        ),
    )

    grant: Mapped["Grant"] = relationship(
        "Grant", back_populates="reimbursements"
    )
