# app/extensions/contracts/ledger_v2.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <set to the relative path of this file>
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v1.0.0  (frozen)
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII in ledger

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.extensions.errors import ContractError
from app.slices.ledger import services as ledger_svc

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "1.0.0"


@dataclass(frozen=True)
class EmitResult:
    ok: bool
    event_id: str
    event_type: str
    chain_key: str


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
) -> EmitResult:
    """
    Canonical ledger write contract.

    Maps provider-level ledger errors to ContractError so that callers see a
    stable, PII-free error surface regardless of the underlying implementation.
    """
    where = "ledger_v2.emit"

    try:
        row = ledger_svc.append_event(
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
    except ledger_svc.EventHashConflict as e:
        raise ContractError(
            code="ledger_hash_conflict",
            where=where,
            message="ledger hash conflict when appending event",
            http_status=503,
            data={"hint": "re-read tail"},
        ) from e
    except ledger_svc.ProviderTemporarilyDown as e:
        raise ContractError(
            code="ledger_unavailable",
            where=where,
            message="ledger provider temporarily unavailable",
            http_status=503,
        ) from e

    return EmitResult(
        ok=True,
        event_id=row.ulid,
        event_type=row.event_type,
        chain_key=row.chain_key,
    )


def verify(chain_key: Optional[str] = None) -> Dict[str, Any]:
    return ledger_svc.verify_chain(chain_key=chain_key)
