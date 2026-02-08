# app/slices/ledger/models.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <set to the relative path of this file>
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v1.0.0  (frozen)
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII in ledger

"""
Ledger slice — canonical, append-only event log (hash-chained, no PII).

This module defines the core LedgerEvent model, which is the single canonical
record of "what happened" across all slices. Every meaningful mutation in the
system should result in exactly one LedgerEvent written via the ledger write
path (event_bus -> extensions.contracts.ledger_v2 -> Ledger services), never by
constructing LedgerEvent rows directly.

Model:

* LedgerEvent
    Append-only event rows keyed by ULID and partitioned by `chain_key`
    (typically a domain-level stream such as "finance.journal" or
    "logistics.issue"). Each event records:
      - domain / operation / event_type: a taxonomy of what happened,
      - actor_ulid / target_ulid: who initiated it and the primary subject,
      - request_id: a required correlation ID tying multiple events to a single
        request or workflow,
      - happened_at_utc: ISO8601 UTC timestamp as a string for consistency
        across languages/tools,
      - refs_json: compact JSON references to related entities/policies
        (e.g., {"customer_ulid": "...", "policy_key": "..."}),
      - changed_json: a compact diff or summary of what changed (keys only,
        no PII or sensitive values),
      - meta_json: optional extra context useful for diagnostics or audits.
    Events are hash-chained via prev_hash_hex / curr_hash_hex, allowing offline
    verification that a chain has not been tampered with. Indexes on
    chain_key, request_id, and event_type support efficient verification and
    querying by stream or workflow.

Ownership and boundaries:

* The Ledger slice owns this table and its invariants; no other slice may
  mutate it directly. All writes must go through the ledger v2 contract and
  associated services so that hashing, chain partitioning, and validation stay
  consistent.
* LedgerEvent must never contain PII or full object snapshots; only ULIDs,
  coarse event types, and normalized JSON refs/changed/meta are allowed.
* Downstream reporting, reconciliation tools, and admin "who did what when"
  views should treat LedgerEvent as the source of truth for system behavior,
  using ULIDs to look up detailed state in slice-local tables when needed.

In short, this module provides the immutable audit spine for VCDB v2: a
hash-chained, PII-free event log that every slice writes to but only Ledger
controls.
"""

from __future__ import annotations

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
    actor_ulid: Mapped[str | None] = mapped_column(String(26))
    target_ulid: Mapped[str | None] = mapped_column(String(26))

    # Request correlation (required)
    request_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # ISO timestamps as strings for consistency
    happened_at_utc: Mapped[str] = mapped_column(String(30), nullable=True)

    # JSON payloads (compact/normalized)
    refs_json: Mapped[str | None] = mapped_column(
        Text
    )  # e.g., {"policy":{...}}
    changed_json: Mapped[str | None] = mapped_column(
        Text
    )  # compact diff/summary
    meta_json: Mapped[str | None] = mapped_column(Text)  # optional extras

    # Hash links (hex-encoded current hash; prev as raw bytes for speed if you prefer)
    prev_hash_hex: Mapped[str | None] = mapped_column(String(64))
    curr_hash_hex: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_ledger_event_chain_key_id", "chain_key"),
        Index("ix_ledger_event_request_id", "request_id"),
        Index("ix_ledger_event_event_type", "event_type"),
    )
