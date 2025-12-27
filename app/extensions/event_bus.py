# app/extensions/event_bus.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# Purpose: Single source of truth for the Ledger write-path surface.
# Ethos: skinny routes, fat services, ULID everywhere, ISO timestamps, NO PII in Ledger.

from __future__ import annotations

from typing import Any, Dict, Optional

from app.extensions.contracts import ledger_v2

# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
# NOTE: Must match Ledger model/service CANON_VERSION.
CANON_VERSION = "1.0.0"

"""
Ledger Event Bus (CANON — do not drift)

This module is intentionally tiny: it defines the single, stable function
signature used to write events to the Ledger across the whole application.

Design constraints:
- Keyword-only API. No positional arguments. This prevents signature drift.
- No renaming. No extra fields. No hidden defaults beyond `None`.
- No slice imports. This must NOT import ledger models/services directly.
  It forwards to the Ledger contract provider only.
- No PII. Ever. Ledger stores ULIDs + small, normalized JSON hints only.

Field rules (hard limits come from LedgerEvent column sizes):

Required:
- domain (str, 1..40)
    Owning slice / domain identifier. Lowercase recommended.
    Examples: "finance", "logistics", "governance", "calendar", "entity".
    Do NOT include dots here.

- operation (str, 1..60)
    What happened, as a stable verb phrase (snake_case recommended).
    Examples: "journal_entry_posted", "sku_issued", "policy_saved".
    Do NOT prefix with domain. (event_type is derived as f"{domain}.{operation}").

- request_id (str, ULID length 26)
    Correlation ID for the request/workflow (CLI invocation, HTTP request, etc.).
    This is REQUIRED so multiple events can be grouped by a single request.

Optional identifiers:
- actor_ulid (str | None, ULID length 26)
    Who initiated the action. May be None for system jobs.

- target_ulid (str | None, ULID length 26)
    Primary subject of the event. May be None when not applicable.

Optional JSON payloads (small, PII-free, JSON-serializable dicts):
- refs (dict | None)
    Compact references to related ULIDs or policy keys.
    Allowed: ULIDs, short strings/enums, ints/bools, small nested dicts/lists.
    NOT allowed: names/addresses/emails/phones/DOB/SSN, object snapshots,
    SQLAlchemy models, big blobs, or user-entered free-text.

- changed (dict | None)
    Compact "what changed" summary. Prefer keys-only or coarse flags.
    Recommended: {"fields": ["status", "amount"], "note": "..."(avoid)}.
    Avoid before/after values if they risk containing PII.

- meta (dict | None)
    Tiny extra context for diagnostics/audit (PII-free).
    Example: {"dry_run": True, "policy_version": "2025-12-22"}.

Timing / partitioning:
- happened_at_utc (str | None, <= 30 chars)
    ISO-8601 UTC timestamp string. If None, the Ledger service will set now.
    Prefer using app.lib.chrono helpers; do not hand-roll formats.

- chain_key (str | None, <= 40 chars)
    Optional partition key for hash chains. If None, Ledger uses `domain`.
    Use only when you intentionally want a separate stream within a domain.
    Example: "finance.journal" (ensure <=40).

Return value:
- Returns whatever the Ledger contract returns (typically the created
  LedgerEvent row or a contract DTO). Callers should not rely on more than
  "it succeeded".

Invariants:
- event_type is DERIVED by Ledger as "{domain}.{operation}" (<= 120 chars).
- This module must remain stable because it is the single choke-point that
  prevents CLI vs HTTP route drift.
"""


def emit(
    *,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: Optional[str],
    target_ulid: Optional[str],
    refs: Optional[Dict[str, Any]] = None,
    changed: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    happened_at_utc: Optional[str] = None,
    chain_key: Optional[str] = None,
):
    """
    Forward a canonical ledger event to the Ledger contract.

    IMPORTANT: This function intentionally performs no transformation.
    Do not rename fields; do not add computed values; do not widen the API.
    All normalization/validation belongs in the Ledger contract/provider.
    """
    return ledger_v2.emit(
        domain=domain,
        operation=operation,
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=target_ulid,
        refs=refs,
        changed=changed,
        meta=meta,
        happened_at_utc=happened_at_utc,
        chain_key=chain_key,
    )


__all__ = ["emit", "CANON_API", "CANON_VERSION"]
