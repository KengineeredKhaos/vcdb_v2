# app/slices/finance/models.py

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.models import ULIDPK, IsoTimestamps

# -----------------
# Canonical
# Vocabularies
# -----------------

FUND_RESTRICTIONS = (
    "unrestricted",
    "temporarily_restricted",
    "permanently_restricted",
)

ACCOUNT_TYPES = (
    "asset",
    "liability",
    "net_assets",
    "revenue",
    "expense",
)

PERIOD_STATUSES = ("open", "soft_closed", "closed")

RESERVE_STATUSES = ("active", "released", "void")
ENCUMBRANCE_STATUSES = ("active", "relieved", "void")
OPS_FLOAT_ACTIONS = ("allocate", "repay", "forgive")
OPS_FLOAT_SUPPORT_MODES = ("seed", "backfill", "bridge")
OPS_FLOAT_STATUSES = ("active", "void")

GRANT_STATUSES = ("draft", "active", "closed", "terminated")
GRANT_FUNDING_MODES = ("reimbursement", "advance")
GRANT_REPORTING_FREQUENCIES = (
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "end_of_term",
)

REIMBURSEMENT_STATUSES = (
    "draft",
    "submitted",
    "approved",
    "denied",
    "paid",
    "closed",
    "void",
)

REIMBURSEMENT_LINE_STATUSES = (
    "included",
    "approved",
    "denied",
    "paid",
    "void",
)

DISBURSEMENT_STATUSES = ("recorded", "voided")
DISBURSEMENT_METHODS = (
    "check",
    "ach",
    "card",
    "cash_external",
    "other",
)


# -----------------
# Reference Tables
# -----------------


class Fund(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_fund"

    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    restriction: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "restriction in "
            "('unrestricted','temporarily_restricted',"
            "'permanently_restricted')",
            name="ck_fund_restriction",
        ),
    )


class Account(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_account"

    code: Mapped[str] = mapped_column(
        String(24), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "type in ('asset','liability','net_assets','revenue','expense')",
            name="ck_account_type",
        ),
    )


class Period(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_period"

    period_key: Mapped[str] = mapped_column(
        String(7), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="open"
    )

    __table_args__ = (
        CheckConstraint(
            "status in ('open','soft_closed','closed')",
            name="ck_period_status",
        ),
    )


# -----------------
# Operational
# Control States
# -----------------


class Reserve(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_reserve"

    funding_demand_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    grant_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="active"
    )
    decision_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    source_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    memo: Mapped[str | None] = mapped_column(String(160), nullable=True)

    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_reserve_nonneg"),
        CheckConstraint(
            "status in ('active','released','void')",
            name="ck_reserve_status",
        ),
    )


class Encumbrance(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_encumbrance"

    funding_demand_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    grant_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    relieved_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="active"
    )
    decision_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    source_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    memo: Mapped[str | None] = mapped_column(String(160), nullable=True)

    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_enc_nonneg"),
        CheckConstraint("relieved_cents >= 0", name="ck_enc_rel_nonneg"),
        CheckConstraint(
            "relieved_cents <= amount_cents",
            name="ck_enc_rel_le_amount",
        ),
        CheckConstraint(
            "status in ('active','relieved','void')",
            name="ck_enc_status",
        ),
    )


class OpsFloat(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_ops_float"

    action: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    support_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    source_funding_demand_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    source_project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    dest_funding_demand_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    dest_project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="active"
    )
    parent_ops_float_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    decision_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    source_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    memo: Mapped[str | None] = mapped_column(String(160), nullable=True)

    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_ops_float_nonneg"),
        CheckConstraint(
            "action in ('allocate','repay','forgive')",
            name="ck_ops_float_action",
        ),
        CheckConstraint(
            "support_mode in ('seed','backfill','bridge')",
            name="ck_ops_float_mode",
        ),
        CheckConstraint(
            "status in ('active','void')",
            name="ck_ops_float_status",
        ),
    )


# -----------------
# Posted Money Spine
# -----------------


class Journal(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_journal"

    source: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    funding_demand_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    grant_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    external_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="USD"
    )
    period_key: Mapped[str] = mapped_column(
        String(7), nullable=False, index=True
    )
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


class JournalLine(db.Model, ULIDPK):
    __tablename__ = "finance_journal_line"

    journal_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_journal.ulid"),
        index=True,
        nullable=False,
    )
    funding_demand_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    grant_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    account_code: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True
    )
    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(160), nullable=True)
    period_key: Mapped[str] = mapped_column(
        String(7), nullable=False, index=True
    )

    journal: Mapped["Journal"] = relationship(
        "Journal", back_populates="lines"
    )

    __table_args__ = (
        CheckConstraint("amount_cents != 0", name="ck_line_nonzero"),
        UniqueConstraint("journal_ulid", "seq", name="uq_journalline_seq"),
    )


# -----------------
# Rebuildable
# Projections
# -----------------


class FinancePostingFact(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_posting_fact"

    journal_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_journal.ulid"),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    posting_family: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    semantic_key: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    method_key: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    funding_demand_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    source_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, index=True
    )
    happened_at_utc: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )
    actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    journal: Mapped["Journal"] = relationship("Journal")

    __table_args__ = (
        CheckConstraint(
            "posting_family in ('income','expense')",
            name="ck_postfact_family",
        ),
        CheckConstraint("amount_cents >= 0", name="ck_postfact_nonneg"),
        UniqueConstraint("journal_ulid", name="uq_postfact_journal"),
    )


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
# Finance-owned
# Admin Issue Spine
# -----------------


class FinanceAdminIssue(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_admin_issue"

    reason_code: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    source_status: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    issue_status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, default="open"
    )
    workflow_key: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )

    target_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    request_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    detection_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    preview_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    resolution_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    opened_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)

    review_started_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    review_started_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    resolved_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    resolved_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    close_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    admin_alert_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    dedupe_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "issue_status in "
            "('open','in_review','resolved','false_positive',"
            "'manual_resolution_required')",
            name="ck_finance_admin_issue_status",
        ),
        db.Index(
            "ix_finance_admin_issue_status_updated",
            "issue_status",
            "updated_at_utc",
        ),
        db.Index(
            "ix_finance_admin_issue_reason_status",
            "reason_code",
            "issue_status",
        ),
        db.Index(
            "ix_finance_admin_issue_request_reason",
            "request_id",
            "reason_code",
        ),
    )


class StatMetric(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_stat_metric"

    period_key: Mapped[str] = mapped_column(
        String(7), nullable=False, index=True
    )
    metric_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
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
# Grant Paperwork &
# Accountability Tables
# -----------------


class Grant(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_grant"

    fund_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    restriction_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, default="unrestricted"
    )
    sponsor_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    project_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    award_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    award_name: Mapped[str] = mapped_column(String(160), nullable=False)
    funding_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="reimbursement"
    )
    amount_awarded_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    match_required_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    start_on: Mapped[str] = mapped_column(String(10), nullable=False)
    end_on: Mapped[str] = mapped_column(String(10), nullable=False)
    reporting_frequency: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    program_income_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    allowable_expense_kinds_raw: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )
    conditions_summary: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    source_document_ref: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="draft"
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reimbursements: Mapped[list["Reimbursement"]] = relationship(
        "Reimbursement",
        back_populates="grant",
        cascade="all, delete-orphan",
        order_by="Reimbursement.submitted_on",
    )

    __table_args__ = (
        CheckConstraint(
            "amount_awarded_cents >= 0",
            name="ck_grant_award_nonneg",
        ),
        CheckConstraint(
            "match_required_cents >= 0",
            name="ck_grant_match_nonneg",
        ),
        CheckConstraint(
            "restriction_type in "
            "('unrestricted','temporarily_restricted',"
            "'permanently_restricted')",
            name="ck_grant_restriction_type",
        ),
        CheckConstraint(
            "funding_mode in ('reimbursement','advance')",
            name="ck_grant_funding_mode",
        ),
        CheckConstraint(
            "reporting_frequency in "
            "('monthly','quarterly','semiannual','annual','end_of_term')",
            name="ck_grant_reporting_frequency",
        ),
        CheckConstraint(
            "status in ('draft','active','closed','terminated')",
            name="ck_grant_status",
        ),
        UniqueConstraint(
            "sponsor_ulid",
            "award_number",
            name="uq_grant_sponsor_award_number",
        ),
    )

    @property
    def allowable_expense_kinds(self) -> list[str]:
        if not self.allowable_expense_kinds_raw:
            return []
        return [
            value
            for value in self.allowable_expense_kinds_raw.split(",")
            if value
        ]

    @allowable_expense_kinds.setter
    def allowable_expense_kinds(self, values: list[str]) -> None:
        cleaned = sorted(
            {
                str(value).strip()
                for value in values or []
                if str(value).strip()
            }
        )
        self.allowable_expense_kinds_raw = ",".join(cleaned)


class Reimbursement(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_reimbursement"

    grant_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_grant.ulid"),
        nullable=False,
        index=True,
    )
    project_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    funding_demand_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    claim_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    period_start: Mapped[str] = mapped_column(String(10), nullable=False)
    period_end: Mapped[str] = mapped_column(String(10), nullable=False)
    submitted_on: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
    decided_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    received_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    claimed_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    approved_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    received_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", index=True
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    grant: Mapped["Grant"] = relationship(
        "Grant", back_populates="reimbursements"
    )
    lines: Mapped[list["ReimbursementLine"]] = relationship(
        "ReimbursementLine",
        back_populates="claim",
        cascade="all, delete-orphan",
        order_by="ReimbursementLine.created_at_utc",
    )

    __table_args__ = (
        CheckConstraint(
            "claimed_amount_cents >= 0",
            name="ck_reimbursement_claimed_nonneg",
        ),
        CheckConstraint(
            "approved_amount_cents >= 0",
            name="ck_reimbursement_approved_nonneg",
        ),
        CheckConstraint(
            "received_amount_cents >= 0",
            name="ck_reimbursement_received_nonneg",
        ),
        CheckConstraint(
            "approved_amount_cents <= claimed_amount_cents",
            name="ck_reimbursement_approved_le_claimed",
        ),
        CheckConstraint(
            "received_amount_cents <= approved_amount_cents",
            name="ck_reimbursement_received_le_approved",
        ),
        CheckConstraint(
            "status in "
            "('draft','submitted','approved','denied','paid',"
            "'closed','void')",
            name="ck_reimbursement_status",
        ),
        UniqueConstraint(
            "grant_ulid",
            "claim_number",
            name="uq_reimbursement_grant_claim_number",
        ),
    )


class ReimbursementLine(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_reimbursement_line"

    claim_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_reimbursement.ulid"),
        nullable=False,
        index=True,
    )
    expense_journal_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_journal.ulid"),
        nullable=False,
        index=True,
    )
    claimed_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    approved_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    received_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="included", index=True
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    claim: Mapped["Reimbursement"] = relationship(
        "Reimbursement", back_populates="lines"
    )
    expense_journal: Mapped["Journal"] = relationship("Journal")

    __table_args__ = (
        CheckConstraint(
            "claimed_amount_cents >= 0",
            name="ck_reimbursement_line_claimed_nonneg",
        ),
        CheckConstraint(
            "approved_amount_cents >= 0",
            name="ck_reimbursement_line_approved_nonneg",
        ),
        CheckConstraint(
            "received_amount_cents >= 0",
            name="ck_reimbursement_line_received_nonneg",
        ),
        CheckConstraint(
            "approved_amount_cents <= claimed_amount_cents",
            name="ck_reimbursement_line_approved_le_claimed",
        ),
        CheckConstraint(
            "received_amount_cents <= approved_amount_cents",
            name="ck_reimbursement_line_received_le_approved",
        ),
        CheckConstraint(
            "status in ('included','approved','denied','paid','void')",
            name="ck_reimbursement_line_status",
        ),
        UniqueConstraint(
            "claim_ulid",
            "expense_journal_ulid",
            name="uq_reimbursement_line_claim_expense",
        ),
    )


class Disbursement(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "finance_disbursement"

    expense_journal_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("finance_journal.ulid"),
        nullable=False,
        index=True,
    )
    grant_ulid: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("finance_grant.ulid"),
        nullable=True,
        index=True,
    )
    project_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )
    funding_demand_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    disbursed_on: Mapped[str] = mapped_column(String(10), nullable=False)
    method: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="other"
    )
    reference: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default="recorded"
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    expense_journal: Mapped["Journal"] = relationship("Journal")
    grant: Mapped["Grant | None"] = relationship("Grant")

    __table_args__ = (
        CheckConstraint(
            "amount_cents >= 0",
            name="ck_disbursement_amount_nonneg",
        ),
        CheckConstraint(
            "method in ('check','ach','card','cash_external','other')",
            name="ck_disbursement_method",
        ),
        CheckConstraint(
            "status in ('recorded','voided')",
            name="ck_disbursement_status",
        ),
    )
