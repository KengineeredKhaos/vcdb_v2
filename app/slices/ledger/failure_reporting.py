# app/slices/ledger/failure_reporting.py

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from flask import current_app

from app.extensions import db
from app.extensions.contracts.admin_v2 import AdminAlertReceiptDTO
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import ensure_request_id

from .admin_issue_services import raise_ledger_admin_issue

REASON_PROVIDER_TEMP_DOWN = "failed_ledger_provider_temporarily_down"
REASON_APPEND_UNAVAILABLE = "failed_ledger_append_unavailable"
REASON_APPEND_CONFLICT = "failed_ledger_append_conflict"
REASON_INTEGRITY_BREAK = "anomaly_ledger_integrity_break"
REASON_IDEMPOTENCY_CONFLICT = "anomaly_ledger_idempotency_conflict"
REASON_UNKNOWN_FAILURE = "failed_ledger_append_unavailable"

_DEFAULT_TITLE = "Ledger write failed"
_DEFAULT_SUMMARY = (
    "An auditable mutation could not be recorded in Ledger. The originating "
    "workflow must fail closed and remain visible for review."
)


def report_ledger_emit_failure_after_rollback(
    *,
    exc: Exception,
    domain: str,
    operation: str,
    request_id: str | None,
    actor_ulid: str | None,
    target_ulid: str | None,
    refs: Mapping[str, Any] | None = None,
    changed: Mapping[str, Any] | None = None,
    meta: Mapping[str, Any] | None = None,
    happened_at_utc: str | None = None,
    chain_key: str | None = None,
    source_context: str | None = None,
    reason_code: str | None = None,
    title: str | None = None,
    summary: str | None = None,
) -> AdminAlertReceiptDTO | None:
    """
    Persist a Ledger-owned self-tattle after a failed emit.

    Intended use from HTTP routes, CLI commands, and system jobs:

        try:
            ... business mutation ...
            event_bus.emit(...)
            db.session.commit()
        except ContractError as exc:
            db.session.rollback()
            if exc.where == "ledger_v2.emit":
                report_ledger_emit_failure_after_rollback(...)
            raise

    This helper deliberately:
    - starts from a rolled-back session boundary,
    - creates/refreshed LedgerAdminIssue truth,
    - upserts admin_alert through the Admin contract,
    - commits that alert transaction immediately,
    - does NOT call event_bus.

    The explicit commit is the point. The original business transaction has
    already failed closed and rolled back, so the self-tattle must survive as
    a separate diagnostic transaction.
    """
    rid = ensure_request_id(request_id)
    clean_domain = str(domain or "unknown").strip() or "unknown"
    clean_operation = str(operation or "unknown").strip() or "unknown"
    clean_chain_key = str(chain_key or clean_domain).strip() or clean_domain
    final_reason = reason_code or _reason_code_for_exception(
        exc,
        meta=meta,
    )

    try:
        db.session.rollback()
    except Exception:
        _log_self_tattle_failure(
            "rollback before Ledger self-tattle failed",
            exc=exc,
            request_id=rid,
            reason_code=final_reason,
        )

    context = build_ledger_emit_failure_context(
        exc=exc,
        domain=clean_domain,
        operation=clean_operation,
        request_id=rid,
        actor_ulid=actor_ulid,
        target_ulid=target_ulid,
        refs=refs,
        changed=changed,
        meta=meta,
        happened_at_utc=happened_at_utc,
        chain_key=clean_chain_key,
        source_context=source_context,
        reason_code=final_reason,
    )

    try:
        receipt = raise_ledger_admin_issue(
            reason_code=final_reason,
            request_id=rid,
            target_ulid=target_ulid,
            chain_key=clean_chain_key,
            actor_ulid=actor_ulid,
            title=title or _DEFAULT_TITLE,
            summary=summary or _DEFAULT_SUMMARY,
            context=context,
        )
        db.session.commit()
        return receipt
    except Exception:
        db.session.rollback()
        _log_self_tattle_failure(
            "Ledger self-tattle failed after emit failure",
            exc=exc,
            request_id=rid,
            reason_code=final_reason,
        )
        return None


def build_ledger_emit_failure_context(
    *,
    exc: Exception,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: str | None,
    target_ulid: str | None,
    refs: Mapping[str, Any] | None,
    changed: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
    happened_at_utc: str | None,
    chain_key: str | None,
    source_context: str | None,
    reason_code: str,
) -> dict[str, Any]:
    """
    Build a compact, PII-resistant diagnostic payload.

    Do not copy refs/changed/meta values into the issue. Some callers may
    accidentally pass payloads that are safe for Ledger but too noisy for an
    Admin queue. Store keys and coarse field names only.
    """
    return {
        "detected_at_utc": now_iso8601_ms(),
        "request_id": request_id,
        "actor_ulid": actor_ulid,
        "target_ulid": target_ulid,
        "domain": domain,
        "operation": operation,
        "event_type": f"{domain}.{operation}",
        "chain_key": chain_key,
        "reason_code": reason_code,
        "contract_code": getattr(exc, "code", None),
        "contract_where": getattr(exc, "where", None),
        "http_status": getattr(exc, "http_status", None),
        "exception_class": exc.__class__.__name__,
        "source_context": source_context,
        "happened_at_utc": happened_at_utc,
        "refs_keys": _mapping_keys(refs),
        "changed_keys": _mapping_keys(changed),
        "changed_fields": _changed_fields(changed),
        "meta_keys": _mapping_keys(meta),
        "idempotency_key_present": _idempotency_key(meta) is not None,
    }


def operator_failure_diagnostics(
    *,
    exc: Exception,
    request_id: str,
    receipt: AdminAlertReceiptDTO | None,
) -> dict[str, Any]:
    """Return a small JSON-safe payload for HTTP/CLI visible failures."""
    return {
        "ok": False,
        "request_id": request_id,
        "code": getattr(exc, "code", "ledger_emit_failed"),
        "where": getattr(exc, "where", None),
        "http_status": getattr(exc, "http_status", 500),
        "admin_alert_ulid": getattr(receipt, "alert_ulid", None),
        "admin_reason_code": getattr(receipt, "reason_code", None),
    }


def _reason_code_for_exception(
    exc: Exception,
    *,
    meta: Mapping[str, Any] | None,
) -> str:
    if isinstance(exc, ContractError):
        code = str(getattr(exc, "code", "") or "").strip().lower()
        if code == "provider_temporarily_down":
            return REASON_PROVIDER_TEMP_DOWN
        if code == "ledger_unavailable":
            return REASON_APPEND_UNAVAILABLE
        if code == "ledger_integrity_error":
            return REASON_INTEGRITY_BREAK
        if code == "event_hash_conflict":
            if _idempotency_key(meta) is not None:
                return REASON_IDEMPOTENCY_CONFLICT
            return REASON_APPEND_CONFLICT
    return REASON_UNKNOWN_FAILURE


def _mapping_keys(value: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    return sorted(str(k) for k in value.keys())


def _changed_fields(changed: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(changed, Mapping):
        return []
    fields = changed.get("fields")
    if isinstance(fields, list):
        return sorted(str(x) for x in fields)
    return []


def _idempotency_key(meta: Mapping[str, Any] | None) -> str | None:
    if not isinstance(meta, Mapping):
        return None
    value = meta.get("idempotency_key")
    clean = str(value or "").strip()
    return clean or None


def _log_self_tattle_failure(
    message: str,
    *,
    exc: Exception,
    request_id: str,
    reason_code: str,
) -> None:
    payload = {
        "request_id": request_id,
        "reason_code": reason_code,
        "original_exception_class": exc.__class__.__name__,
        "contract_code": getattr(exc, "code", None),
        "contract_where": getattr(exc, "where", None),
    }
    try:
        current_app.logger.exception(message, extra={"vcdb": payload})
    except RuntimeError:
        logging.getLogger(__name__).exception("%s %r", message, payload)


__all__ = [
    "report_ledger_emit_failure_after_rollback",
    "build_ledger_emit_failure_context",
    "operator_failure_diagnostics",
    "REASON_PROVIDER_TEMP_DOWN",
    "REASON_APPEND_UNAVAILABLE",
    "REASON_APPEND_CONFLICT",
    "REASON_INTEGRITY_BREAK",
    "REASON_IDEMPOTENCY_CONFLICT",
]
