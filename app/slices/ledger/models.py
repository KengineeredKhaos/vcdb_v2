# app/slices/ledger/models.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <set to the relative path of this file>
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v1.0.0  (frozen)
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII in ledger
from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import ULIDPK, IsoTimestamps

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "1.0.0"


class LedgerEvent(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "ledger_event"

    # Chain partition (default: domain); helps verify subsets independently
    chain_key: Mapped[str] = mapped_column(String(40), nullable=False)

    # Taxonomy (domain.operation) kept both split and joined for convenience
    domain: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)

    # Actor/target ULIDs (may be None)
    actor_ulid: Mapped[Optional[str]] = mapped_column(String(26))
    target_ulid: Mapped[Optional[str]] = mapped_column(String(26))

    # Request correlation (required)
    request_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # ISO timestamps as strings for consistency
    happened_at_utc: Mapped[str] = mapped_column(String(30), nullable=True)

    # JSON payloads (compact/normalized)
    refs_json: Mapped[Optional[str]] = mapped_column(
        Text
    )  # e.g., {"policy":{...}}
    changed_json: Mapped[Optional[str]] = mapped_column(
        Text
    )  # compact diff/summary
    meta_json: Mapped[Optional[str]] = mapped_column(Text)  # optional extras

    # Hash links (hex-encoded current hash; prev as raw bytes for speed if you prefer)
    prev_hash_hex: Mapped[Optional[str]] = mapped_column(String(64))
    curr_hash_hex: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_ledger_event_chain_key_id", "chain_key"),
        Index("ix_ledger_event_request_id", "request_id"),
        Index("ix_ledger_event_event_type", "event_type"),
    )
