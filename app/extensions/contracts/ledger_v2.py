# app/extensions/contracts/ledger_v2.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <set to the relative path of this file>
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v1.0.0  (frozen)
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII in ledger

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.extensions.errors import ContractError
from app.slices.ledger import services as ledger_svc
from app.slices.ledger.errors import (
    EventHashConflict,
    LedgerBadArgument,
    LedgerIntegrityError,
    LedgerUnavailable,
    ProviderTemporarilyDown,
)

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "2.0.0"


@dataclass(frozen=True)
class EmitResult:
    ok: bool
    event_id: str
    event_type: str
    chain_key: str


@dataclass(frozen=True)
class LedgerIntegritySummaryDTO:
    has_gate_record: bool
    gate_check_ulid: str | None
    gate_reason_code: str | None
    gate_source_status: str | None
    routine_backup_allowed: bool
    dirty_forensic_backup_only: bool
    last_check_at_utc: str | None
    last_repair_at_utc: str | None
    open_issue_count: int
    failed_open_issue_count: int
    anomaly_open_issue_count: int


def emit(
    *,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: str | None,
    target_ulid: str | None,
    refs: dict[str, Any] | None = None,
    changed: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    happened_at_utc: str | None = None,
    chain_key: str | None = None,
) -> EmitResult:
    """
    Canonical ledger write contract.

    Maps provider-level ledger errors to ContractError so that callers
    see a stable, PII-free error surface regardless of the underlying
    implementation.
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
    except LedgerBadArgument as exc:
        raise ContractError(
            code="bad_argument",
            where=where,
            message=str(exc),
            http_status=400,
        ) from exc
    except EventHashConflict as exc:
        raise ContractError(
            code="event_hash_conflict",
            where=where,
            message=str(exc) or "ledger event hash conflict",
            http_status=409,
        ) from exc
    except ProviderTemporarilyDown as exc:
        raise ContractError(
            code="provider_temporarily_down",
            where=where,
            message=str(exc) or "ledger provider temporarily down",
            http_status=503,
        ) from exc
    except LedgerUnavailable as exc:
        raise ContractError(
            code="ledger_unavailable",
            where=where,
            message=str(exc) or "ledger provider unavailable",
            http_status=503,
        ) from exc
    except Exception as exc:
        raise ContractError(
            code="internal_error",
            where=where,
            message=f"unexpected: {exc.__class__.__name__}",
            http_status=500,
        ) from exc

    return EmitResult(
        ok=True,
        event_id=row.ulid,
        event_type=row.event_type,
        chain_key=row.chain_key,
    )


def verify(chain_key: str | None = None) -> dict[str, Any]:
    where = "ledger_v2.verify"

    try:
        return ledger_svc.verify_chain(chain_key=chain_key)
    except LedgerBadArgument as exc:
        raise ContractError(
            code="bad_argument",
            where=where,
            message=str(exc),
            http_status=400,
        ) from exc
    except LedgerIntegrityError as exc:
        raise ContractError(
            code="ledger_integrity_error",
            where=where,
            message=str(exc) or "ledger integrity error",
            http_status=409,
        ) from exc
    except ProviderTemporarilyDown as exc:
        raise ContractError(
            code="provider_temporarily_down",
            where=where,
            message=str(exc) or "ledger provider temporarily down",
            http_status=503,
        ) from exc
    except LedgerUnavailable as exc:
        raise ContractError(
            code="ledger_unavailable",
            where=where,
            message=str(exc) or "ledger provider unavailable",
            http_status=503,
        ) from exc
    except Exception as exc:
        raise ContractError(
            code="internal_error",
            where=where,
            message=f"unexpected: {exc.__class__.__name__}",
            http_status=500,
        ) from exc


def get_integrity_summary() -> LedgerIntegritySummaryDTO:
    where = "ledger_v2.get_integrity_summary"

    try:
        raw = ledger_svc.get_integrity_summary()
        return LedgerIntegritySummaryDTO(
            has_gate_record=bool(raw.get("has_gate_record")),
            gate_check_ulid=raw.get("gate_check_ulid"),
            gate_reason_code=raw.get("gate_reason_code"),
            gate_source_status=raw.get("gate_source_status"),
            routine_backup_allowed=bool(
                raw.get("routine_backup_allowed", False)
            ),
            dirty_forensic_backup_only=bool(
                raw.get("dirty_forensic_backup_only", True)
            ),
            last_check_at_utc=raw.get("last_check_at_utc"),
            last_repair_at_utc=raw.get("last_repair_at_utc"),
            open_issue_count=int(raw.get("open_issue_count") or 0),
            failed_open_issue_count=int(
                raw.get("failed_open_issue_count") or 0
            ),
            anomaly_open_issue_count=int(
                raw.get("anomaly_open_issue_count") or 0
            ),
        )
    except ProviderTemporarilyDown as exc:
        raise ContractError(
            code="provider_temporarily_down",
            where=where,
            message=str(exc) or "ledger provider temporarily down",
            http_status=503,
        ) from exc
    except LedgerUnavailable as exc:
        raise ContractError(
            code="ledger_unavailable",
            where=where,
            message=str(exc) or "ledger provider unavailable",
            http_status=503,
        ) from exc
    except Exception as exc:
        raise ContractError(
            code="internal_error",
            where=where,
            message=f"unexpected: {exc.__class__.__name__}",
            http_status=500,
        ) from exc