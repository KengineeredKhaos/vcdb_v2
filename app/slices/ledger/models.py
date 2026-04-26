# app/slices/ledger/models.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: app/slices/ledger/models.py
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v2.1.0
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII

"""
Ledger slice — append-only event log plus hash-chain accountability.

LedgerEvent records PII-free audit facts. Hash-chain fields provide
sequence/tamper evidence for those facts. A broken/forked hash chain is
survivable, but it is never invisible: LedgerHashchainCheck,
LedgerHashchainRepair, and LedgerAdminIssue preserve the good, bad, and ugly
for Admin launch and Auditor read-only drill-down.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import IsoTimestamps, ULIDPK

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "2.1.0"


class LedgerEvent(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "ledger_event"

    # Chain partition (default: domain); verifies subsets independently.
    chain_key: Mapped[str] = mapped_column(String(40), nullable=False)

    # Deterministic position within a chain. Timestamps are not sequence.
    chain_seq: Mapped[int] = mapped_column(Integer, nullable=False)

    # Taxonomy (domain.operation) kept split and joined for convenience.
    domain: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)

    # Actor/target ULIDs (may be None).
    actor_ulid: Mapped[str | None] = mapped_column(String(26))
    target_ulid: Mapped[str | None] = mapped_column(String(26))

    # Request correlation (required).
    request_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # ISO timestamps as strings for consistency.
    happened_at_utc: Mapped[str] = mapped_column(String(30), nullable=True)

    # JSON payloads (compact/normalized, PII-free).
    refs_json: Mapped[str | None] = mapped_column(Text)
    changed_json: Mapped[str | None] = mapped_column(Text)
    meta_json: Mapped[str | None] = mapped_column(Text)

    # Hash links.
    prev_hash_hex: Mapped[str | None] = mapped_column(String(64))
    curr_hash_hex: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "chain_key",
            "chain_seq",
            name="uq_ledger_event_chain_seq",
        ),
        Index("ix_ledger_event_chain_key_seq", "chain_key", "chain_seq"),
        Index("ix_ledger_event_chain_key_id", "chain_key"),
        Index("ix_ledger_event_request_id", "request_id"),
        Index("ix_ledger_event_event_type", "event_type"),
    )


class LedgerAdminIssue(db.Model, ULIDPK, IsoTimestamps):
    """
    Slice-local Ledger issue truth for Admin/Auditor visibility.

    Admin owns queue posture and launch. Ledger owns facts, diagnostics,
    verification posture, repair mechanics, and terminal state.
    """

    __tablename__ = "ledger_admin_issue"

    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_status: Mapped[str] = mapped_column(String(64), nullable=False)

    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)
    chain_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)

    requested_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    resolved_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict[str, object]] = mapped_column(
        db.JSON, nullable=False, default=dict
    )

    closed_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    close_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_ledger_admin_issue_open",
            "source_status",
            "updated_at_utc",
        ),
        Index(
            "ix_ledger_admin_issue_request_reason",
            "request_id",
            "reason_code",
        ),
        Index(
            "ix_ledger_admin_issue_chain",
            "chain_key",
            "reason_code",
        ),
    )


class LedgerHashchainCheck(db.Model, ULIDPK, IsoTimestamps):
    """
    Evidence row for verify/daily-close/cron hash-chain checks.

    Clean checks, anomalies, failures, and repaired/reconciled checks all land
    here so Auditor can inspect system health without mutating anything.
    """

    __tablename__ = "ledger_hashchain_check"

    check_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_status: Mapped[str] = mapped_column(String(64), nullable=False)

    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)
    chain_key: Mapped[str | None] = mapped_column(String(40), nullable=True)

    started_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    completed_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)

    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checked_count: Mapped[int] = mapped_column(Integer, nullable=False)
    anomaly_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)

    routine_backup_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    dirty_forensic_backup_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    details_json: Mapped[dict[str, object]] = mapped_column(
        db.JSON, nullable=False, default=dict
    )

    __table_args__ = (
        Index(
            "ix_ledger_hashchain_check_kind_created",
            "check_kind",
            "created_at_utc",
        ),
        Index(
            "ix_ledger_hashchain_check_reason",
            "reason_code",
            "source_status",
        ),
    )


class LedgerHashchainRepair(db.Model, ULIDPK, IsoTimestamps):
    """
    Evidence row for Ledger-owned hash-chain repair/reconciliation work.

    Repairs are not hidden cleanup. They are operational events with before
    and after verification evidence available to Admin and Auditor.
    """

    __tablename__ = "ledger_hashchain_repair"

    repair_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_status: Mapped[str] = mapped_column(String(64), nullable=False)

    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)
    issue_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)
    check_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)
    chain_key: Mapped[str | None] = mapped_column(String(40), nullable=True)

    started_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    completed_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    before_json: Mapped[dict[str, object]] = mapped_column(
        db.JSON, nullable=False, default=dict
    )
    after_json: Mapped[dict[str, object]] = mapped_column(
        db.JSON, nullable=False, default=dict
    )
    affected_event_ulids_json: Mapped[list[str]] = mapped_column(
        db.JSON, nullable=False, default=list
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index(
            "ix_ledger_hashchain_repair_chain",
            "chain_key",
            "created_at_utc",
        ),
        Index(
            "ix_ledger_hashchain_repair_issue",
            "issue_ulid",
        ),
    )
