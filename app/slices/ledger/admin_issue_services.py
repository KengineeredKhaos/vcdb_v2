# app/slices/ledger/admin_issue_services.py

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, or_, select

from app.extensions import db, event_bus
from app.extensions.contracts.admin_v2 import (
    AdminAlertCloseDTO,
    AdminAlertReceiptDTO,
    AdminAlertUpsertDTO,
    AdminResolutionTargetDTO,
    close_alert,
    upsert_alert,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import ensure_request_id

from .models import (
    LedgerAdminIssue,
    LedgerHashchainCheck,
    LedgerHashchainRepair,
)
from .services import (
    CHECK_KIND_MANUAL_VERIFY,
    REASON_ADVISORY_CRON_LEDGERCHECK,
    REASON_ADVISORY_HASHCHAIN,
    REASON_ANOMALY_HASHCHAIN,
    REASON_FAILURE_CRON_LEDGERCHECK,
    REASON_FAILURE_HASHCHAIN,
    latest_daily_close_status,
    record_hashchain_check,
    repair_hashchain,
    verify_chain,
)

SOURCE_STATUS_OPEN = "open"
SOURCE_STATUS_INVESTIGATING = "investigating"
SOURCE_STATUS_RESTORED = "restored"
SOURCE_STATUS_NO_REPAIR = "closed_no_repair"
SOURCE_STATUS_ADVISORY = "advisory_recorded"
SOURCE_STATUS_UNRECONCILED = "unreconciled"
SOURCE_STATUS_FAILURE = "failure"
SOURCE_STATUS_SUPERSEDED = "superseded"

ADMIN_STATUS_RESOLVED = "resolved"
ADMIN_STATUS_SOURCE_CLOSED = "source_closed"

WORKFLOW_KEY = "ledger_admin_issue"

HASHCHAIN_ATTENTION_REASONS = frozenset(
    {
        REASON_ANOMALY_HASHCHAIN,
        REASON_FAILURE_HASHCHAIN,
        REASON_FAILURE_CRON_LEDGERCHECK,
    }
)

HASHCHAIN_ADVISORY_REASONS = frozenset(
    {
        REASON_ADVISORY_HASHCHAIN,
        REASON_ADVISORY_CRON_LEDGERCHECK,
    }
)

HASHCHAIN_REASON_CODES = (
    HASHCHAIN_ATTENTION_REASONS | HASHCHAIN_ADVISORY_REASONS
)


def sync_hashchain_issue_from_check(
    *,
    check: LedgerHashchainCheck,
    result: dict[str, Any],
    actor_ulid: str | None,
) -> AdminAlertReceiptDTO | None:
    """
    Sync Ledger-owned issue truth after a hash-chain check.

    Admin Inbox is for attention/action, not routine success notices:
    - clean/advisory checks remain evidence rows only
    - clean/advisory checks close matching open Ledger issues
    - anomaly/failure checks create or refresh an Admin alert
    """
    if check.ok or check.reason_code in HASHCHAIN_ADVISORY_REASONS:
        close_open_hashchain_issues_from_check(
            check=check,
            result=result,
            actor_ulid=actor_ulid,
        )
        return None

    return raise_hashchain_issue_from_check(
        check=check,
        result=result,
        actor_ulid=actor_ulid,
    )


def raise_ledger_admin_issue(
    *,
    reason_code: str,
    request_id: str | None,
    target_ulid: str | None = None,
    chain_key: str | None = None,
    event_ulid: str | None = None,
    actor_ulid: str | None = None,
    title: str,
    summary: str,
    context: dict[str, Any] | None = None,
    source_status: str = SOURCE_STATUS_OPEN,
    upsert_admin_alert: bool = True,
) -> AdminAlertReceiptDTO | None:
    """
    Create or refresh Ledger-owned issue truth and optionally cue Admin.

    Hash-chain issues dedupe by open chain/reason, not by the daily close
    request_id. That prevents every daily check from spamming a fresh Admin
    Inbox item for the same unresolved Ledger condition.

    No commit here. Caller owns the transaction boundary.
    """
    rid = ensure_request_id(request_id)

    if reason_code in HASHCHAIN_ATTENTION_REASONS:
        issue = _get_open_hashchain_issue(
            chain_key=chain_key,
            reason_code=reason_code,
        )
    else:
        issue = _get_open_issue(
            request_id=rid,
            target_ulid=target_ulid,
            reason_code=reason_code,
            chain_key=chain_key,
        )

    if issue is None:
        issue = _create_issue(
            reason_code=reason_code,
            request_id=rid,
            target_ulid=target_ulid,
            chain_key=chain_key,
            event_ulid=event_ulid,
            actor_ulid=actor_ulid,
            title=title,
            summary=summary,
            context=context,
            source_status=source_status,
        )
    else:
        issue.title = title
        issue.summary = summary
        issue.source_status = source_status
        issue.event_ulid = event_ulid or issue.event_ulid
        issue.details_json = dict(context or issue.details_json or {})
        issue.updated_at_utc = now_iso8601_ms()
        db.session.flush()

    if reason_code in HASHCHAIN_ATTENTION_REASONS:
        _supersede_other_hashchain_issues(
            current_issue=issue,
            actor_ulid=actor_ulid,
            superseded_by_reason=reason_code,
        )

    if not upsert_admin_alert:
        return None
    return _upsert_admin_alert(issue)


def raise_hashchain_issue_from_check(
    *,
    check: LedgerHashchainCheck,
    result: dict[str, Any],
    actor_ulid: str | None,
) -> AdminAlertReceiptDTO | None:
    """Raise/refresh Admin attention only for anomaly/failure checks."""
    if check.ok or check.reason_code not in HASHCHAIN_ATTENTION_REASONS:
        close_open_hashchain_issues_from_check(
            check=check,
            result=result,
            actor_ulid=actor_ulid,
        )
        return None

    title, summary, source_status = _message_for_check(check)
    broken = result.get("broken") or {}
    event_ulid = None
    event_ulid = _first_failure_event_ulid(result)

    return raise_ledger_admin_issue(
        reason_code=check.reason_code,
        request_id=check.request_id,
        target_ulid=None,
        chain_key=check.chain_key,
        event_ulid=event_ulid,
        actor_ulid=actor_ulid,
        title=title,
        summary=summary,
        source_status=source_status,
        context=_build_check_context(check=check, result=result),
    )


def close_open_hashchain_issues_from_check(
    *,
    check: LedgerHashchainCheck,
    result: dict[str, Any],
    actor_ulid: str | None,
) -> list[AdminAlertReceiptDTO]:
    """
    Close matching open Ledger hash-chain issues after a clean check.

    This does not create a new Admin alert. Clean daily close is business as
    usual. The clean check row is the audit evidence; the issue close removes
    stale Admin attention from the queue.
    """
    if not check.ok:
        return []

    receipts: list[AdminAlertReceiptDTO] = []
    for issue in _get_open_hashchain_issues(chain_key=check.chain_key):
        receipts.append(
            _close_issue_from_check(
                issue=issue,
                check=check,
                result=result,
                actor_ulid=actor_ulid,
                close_reason="restored_by_clean_hashchain_check",
            )
        )
    return receipts


def raise_hashchain_advisory(
    *,
    request_id: str | None,
    actor_ulid: str | None,
    chain_key: str | None,
    title: str,
    summary: str,
    context: dict[str, Any] | None = None,
) -> AdminAlertReceiptDTO | None:
    """
    Deprecated compatibility hook.

    Clean/advisory Ledger outcomes are evidence records, not Admin Inbox work.
    Keep this function so older callers do not fail, but do not create a
    LedgerAdminIssue/admin_alert from a routine success notice.
    """
    return None


def ledger_drilldown_index(
    *,
    view: str = "active",
    limit: int = 20,
) -> dict[str, Any]:
    clean_view = _clean_issue_view(view)
    issues = _list_issues(view=clean_view, limit=limit)
    checks = _list_checks(limit=limit)
    repairs = _list_repairs(limit=limit)
    gate_status = latest_daily_close_status()

    return {
        "title": "Ledger integrity drill-down",
        "summary": (
            "Ledger owns integrity truth, evidence, and repair history. "
            "Admin launches Ledger-owned actions. Auditor reads."
        ),
        "current_view": clean_view,
        "gate_status": gate_status,
        "issues": tuple(_issue_index_row(row) for row in issues),
        "checks": tuple(_check_index_row(row) for row in checks),
        "repairs": tuple(_repair_index_row(row) for row in repairs),
    }


def run_manual_integrity_check(
    *,
    actor_ulid: str | None,
    request_id: str | None,
    chain_key: str | None = None,
) -> dict[str, Any]:
    """
    Run an Admin-initiated Ledger inspection from the drill-down landing page.

    This is evidence-only. It records a manual verify check row and may
    create or refresh a Ledger admin issue when dirty, but it does not
    reopen the backup gate.
    """
    rid = ensure_request_id(request_id)
    started = now_iso8601_ms()
    result = verify_chain(chain_key=chain_key)

    broken = result.get("broken") or {}
    derived_chain_key = (
        chain_key or str(broken.get("chain_key") or "").strip() or None
    )

    check = record_hashchain_check(
        check_kind=CHECK_KIND_MANUAL_VERIFY,
        result=result,
        request_id=rid,
        actor_ulid=actor_ulid,
        issue_ulid=None,
        chain_key=derived_chain_key,
        started_at_utc=started,
    )
    receipt = sync_hashchain_issue_from_check(
        check=check,
        result=result,
        actor_ulid=actor_ulid,
    )
    return {
        "ok": bool(result.get("ok")),
        "check_ulid": check.ulid,
        "chain_key": derived_chain_key,
        "alert_queued": bool(receipt),
    }


def ledger_issue_get(issue_ulid: str) -> dict[str, Any]:
    issue = _get_issue_or_raise(issue_ulid)
    details = dict(issue.details_json or {})
    related_checks = _list_checks(issue_ulid=issue.ulid, limit=10)
    related_repairs = _list_repairs(issue_ulid=issue.ulid, limit=10)
    return {
        "title": issue.title,
        "summary": issue.summary,
        "issue_ulid": issue.ulid,
        "reason_code": issue.reason_code,
        "source_status": issue.source_status,
        "request_id": issue.request_id,
        "target_ulid": issue.target_ulid,
        "chain_key": issue.chain_key,
        "event_ulid": issue.event_ulid or _first_failure_event_ulid(details),
        "details": details,
        "closed_at_utc": issue.closed_at_utc,
        "close_reason": issue.close_reason,
        "backup_posture": _backup_posture(issue),
        "allowed_actions": _allowed_actions(issue),
        "last_verify_check_ulid": _latest_detail_check_ulid(details),
        "last_repair_ulid": _latest_detail_repair_ulid(details),
        "related_checks": tuple(
            _check_index_row(row) for row in related_checks
        ),
        "related_repairs": tuple(
            _repair_index_row(row) for row in related_repairs
        ),
        "as_of_utc": now_iso8601_ms(),
    }


def ledger_check_get(check_ulid: str) -> dict[str, Any]:
    check = _get_check_or_raise(check_ulid)
    issue = _get_issue_optional(check.issue_ulid)
    repairs = _list_repairs_for_check(check.ulid)

    return {
        "title": f"Ledger check — {check.check_kind}",
        "summary": "Ledger hash-chain evidence row.",
        "check_ulid": check.ulid,
        "issue_ulid": check.issue_ulid,
        "issue_title": issue.title if issue else None,
        "reason_code": check.reason_code,
        "source_status": check.source_status,
        "request_id": check.request_id,
        "actor_ulid": check.actor_ulid,
        "chain_key": check.chain_key,
        "check_kind": check.check_kind,
        "started_at_utc": check.started_at_utc,
        "completed_at_utc": check.completed_at_utc,
        "ok": bool(check.ok),
        "checked_count": check.checked_count,
        "anomaly_count": check.anomaly_count,
        "failure_count": check.failure_count,
        "routine_backup_allowed": bool(check.routine_backup_allowed),
        "dirty_forensic_backup_only": bool(check.dirty_forensic_backup_only),
        "details": check.details_json or {},
        "related_repairs": tuple(_repair_index_row(row) for row in repairs),
    }


def ledger_repair_get(repair_ulid: str) -> dict[str, Any]:
    repair = _get_repair_or_raise(repair_ulid)
    issue = _get_issue_optional(repair.issue_ulid)

    return {
        "title": "Ledger repair evidence",
        "summary": "Ledger-owned hash-chain repair record.",
        "repair_ulid": repair.ulid,
        "issue_ulid": repair.issue_ulid,
        "issue_title": issue.title if issue else None,
        "repair_kind": repair.repair_kind,
        "reason_code": repair.reason_code,
        "source_status": repair.source_status,
        "request_id": repair.request_id,
        "actor_ulid": repair.actor_ulid,
        "chain_key": repair.chain_key,
        "source_check_ulid": repair.source_check_ulid,
        "post_repair_check_ulid": repair.post_repair_check_ulid,
        "started_at_utc": repair.started_at_utc,
        "completed_at_utc": repair.completed_at_utc,
        "summary_text": repair.summary,
        "affected_event_ulids": tuple(repair.affected_event_ulids_json or ()),
        "affected_count": len(repair.affected_event_ulids_json or ()),
        "before": repair.before_json or {},
        "after": repair.after_json or {},
    }


def run_verify_for_issue(
    *,
    issue_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    """Run investigation verify for the issue chain and record evidence."""
    rid = ensure_request_id(request_id)
    issue = _get_issue_or_raise(issue_ulid)
    started = now_iso8601_ms()
    result = verify_chain(chain_key=issue.chain_key)
    check = record_hashchain_check(
        check_kind=CHECK_KIND_MANUAL_VERIFY,
        result=result,
        request_id=rid,
        actor_ulid=actor_ulid,
        issue_ulid=issue.ulid,
        chain_key=issue.chain_key,
        started_at_utc=started,
    )

    details = dict(issue.details_json or {})
    details["last_verify"] = _build_check_context(
        check=check,
        result=result,
    )
    issue.details_json = details

    changed_fields = ["details_json"]
    if (
        not result.get("ok")
        and issue.source_status != SOURCE_STATUS_INVESTIGATING
    ):
        issue.source_status = SOURCE_STATUS_INVESTIGATING
        changed_fields.append("source_status")

    issue.updated_at_utc = now_iso8601_ms()

    event_bus.emit(
        domain="ledger",
        operation="admin_issue_verify_run",
        actor_ulid=actor_ulid,
        target_ulid=issue.target_ulid,
        request_id=rid,
        refs={
            "issue_ulid": issue.ulid,
            "chain_key": issue.chain_key,
            "event_ulid": issue.event_ulid,
            "check_ulid": check.ulid,
        },
        changed={"fields": changed_fields},
        meta={
            "origin": "ledger_admin_issue",
            "reason_code": issue.reason_code,
            "verify_ok": bool(result.get("ok")),
            "check_kind": CHECK_KIND_MANUAL_VERIFY,
        },
        happened_at_utc=now_iso8601_ms(),
        chain_key="ledger.health",
    )
    db.session.flush()
    return result


def repair_hashchain_for_issue(
    *,
    issue_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    """Repair the issue chain, record evidence, and close if restored."""
    rid = ensure_request_id(request_id)
    issue = _get_issue_or_raise(issue_ulid)
    if issue.closed_at_utc:
        raise ValueError("Ledger admin issue is already closed")
    if not issue.chain_key:
        raise ValueError("Ledger hash-chain repair requires chain_key")

    details = dict(issue.details_json or {})
    last_verify = details.get("last_verify") or {}
    source_check_ulid = None
    if isinstance(last_verify, dict):
        source_check_ulid = str(last_verify.get("check_ulid") or "") or None
    source_check_ulid = source_check_ulid or (
        str(details.get("check_ulid") or "") or None
    )

    result = repair_hashchain(
        chain_key=issue.chain_key,
        actor_ulid=actor_ulid,
        request_id=rid,
        issue_ulid=issue.ulid,
        source_check_ulid=source_check_ulid,
    )

    updated_details = dict(issue.details_json or {})
    updated_details["last_repair"] = result
    updated_details["last_repair_at_utc"] = now_iso8601_ms()
    issue.details_json = updated_details
    issue.event_ulid = issue.event_ulid or _first_failure_event_ulid(
        updated_details
    )
    issue.updated_at_utc = now_iso8601_ms()

    if result.get("ok"):
        close_ledger_admin_issue(
            issue_ulid=issue.ulid,
            actor_ulid=actor_ulid,
            request_id=rid,
            source_status=SOURCE_STATUS_RESTORED,
            close_reason="hashchain_repaired",
        )
    else:
        issue.source_status = SOURCE_STATUS_FAILURE
        issue.updated_at_utc = now_iso8601_ms()
        _upsert_admin_alert(issue)
        db.session.flush()

    return result


def close_ledger_admin_issue(
    *,
    issue_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
    source_status: str,
    close_reason: str,
    admin_status: str = ADMIN_STATUS_RESOLVED,
) -> AdminAlertReceiptDTO | None:
    """Close Ledger-owned issue truth and close the Admin alert."""
    rid = ensure_request_id(request_id)
    issue = _get_issue_or_raise(issue_ulid)
    now = now_iso8601_ms()

    if issue.closed_at_utc:
        return close_alert(
            AdminAlertCloseDTO(
                source_slice="ledger",
                reason_code=issue.reason_code,
                request_id=issue.request_id,
                target_ulid=issue.target_ulid,
                source_status=issue.source_status,
                close_reason="already_terminal",
                admin_status=ADMIN_STATUS_SOURCE_CLOSED,
            )
        )

    issue.source_status = source_status
    issue.resolved_by_actor_ulid = actor_ulid
    issue.closed_at_utc = now
    issue.close_reason = close_reason
    issue.updated_at_utc = now

    receipt = close_alert(
        AdminAlertCloseDTO(
            source_slice="ledger",
            reason_code=issue.reason_code,
            request_id=issue.request_id,
            target_ulid=issue.target_ulid,
            source_status=source_status,
            close_reason=close_reason,
            admin_status=admin_status,
        )
    )

    event_bus.emit(
        domain="ledger",
        operation="admin_issue_closed",
        actor_ulid=actor_ulid,
        target_ulid=issue.target_ulid,
        request_id=rid,
        refs={
            "issue_ulid": issue.ulid,
            "chain_key": issue.chain_key,
            "event_ulid": issue.event_ulid,
        },
        changed={"fields": ["source_status", "closed_at_utc"]},
        meta={
            "origin": "ledger_admin_issue",
            "reason_code": issue.reason_code,
            "close_reason": close_reason,
        },
        happened_at_utc=now,
        chain_key="ledger.health",
    )
    db.session.flush()
    return receipt


# -----------------
# Internal helpers
# -----------------


def _first_failure_event_ulid(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None

    failures = payload.get("failures") or []
    if isinstance(failures, list):
        for failure in failures:
            if isinstance(failure, dict) and failure.get("event_ulid"):
                return str(failure["event_ulid"])

    broken = payload.get("broken") or {}
    if isinstance(broken, dict) and broken.get("event_ulid"):
        return str(broken["event_ulid"])

    details = payload.get("details") or {}
    if isinstance(details, dict):
        return _first_failure_event_ulid(details)

    return None


def _message_for_check(
    check: LedgerHashchainCheck,
) -> tuple[str, str, str]:
    if check.reason_code == REASON_FAILURE_CRON_LEDGERCHECK:
        return (
            "Ledger daily check failed",
            (
                "The scheduled Ledger hash-chain check did not complete "
                "cleanly. Routine backup/archive is blocked until Ledger "
                "can verify or the dirty state is explicitly preserved."
            ),
            SOURCE_STATUS_FAILURE,
        )

    if check.reason_code == REASON_FAILURE_HASHCHAIN:
        return (
            "Ledger hash-chain failure detected",
            (
                "Ledger daily close found a hash-chain verification "
                "failure. Routine backup/archive is blocked. Dirty forensic "
                "backup remains available. Open the Ledger issue to review "
                "evidence and next steps."
            ),
            SOURCE_STATUS_FAILURE,
        )

    return (
        "Ledger hash-chain anomaly detected",
        (
            "Ledger detected a survivable hash-chain anomaly. Operations "
            "may continue, but routine backup/archive remains blocked until "
            "Ledger verifies clean or reconciliation evidence is recorded."
        ),
        SOURCE_STATUS_UNRECONCILED,
    )


def _build_check_context(
    *,
    check: LedgerHashchainCheck,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "check_ulid": check.ulid,
        "issue_ulid": check.issue_ulid,
        "reason_code": check.reason_code,
        "check_kind": check.check_kind,
        "source_status": check.source_status,
        "chain_key": check.chain_key,
        "routine_backup_allowed": check.routine_backup_allowed,
        "dirty_forensic_backup_only": check.dirty_forensic_backup_only,
        "checked": check.checked_count,
        "anomaly_count": check.anomaly_count,
        "failure_count": check.failure_count,
        "anomalies": result.get("anomalies") or [],
        "failures": result.get("failures") or [],
        "broken": result.get("broken"),
        "completed_at_utc": check.completed_at_utc,
    }


def _close_issue_from_check(
    *,
    issue: LedgerAdminIssue,
    check: LedgerHashchainCheck,
    result: dict[str, Any],
    actor_ulid: str | None,
    close_reason: str,
) -> AdminAlertReceiptDTO | None:
    now = now_iso8601_ms()
    details = dict(issue.details_json or {})
    details["restoring_check"] = _build_check_context(
        check=check,
        result=result,
    )
    issue.details_json = details
    issue.source_status = SOURCE_STATUS_RESTORED
    issue.resolved_by_actor_ulid = actor_ulid
    issue.closed_at_utc = now
    issue.close_reason = close_reason
    issue.updated_at_utc = now

    receipt = close_alert(
        AdminAlertCloseDTO(
            source_slice="ledger",
            reason_code=issue.reason_code,
            request_id=issue.request_id,
            target_ulid=issue.target_ulid,
            source_status=SOURCE_STATUS_RESTORED,
            close_reason=close_reason,
            admin_status=ADMIN_STATUS_RESOLVED,
            closed_at_utc=now,
        )
    )
    db.session.flush()
    return receipt


def _supersede_other_hashchain_issues(
    *,
    current_issue: LedgerAdminIssue,
    actor_ulid: str | None,
    superseded_by_reason: str,
) -> None:
    for issue in _get_open_hashchain_issues(
        chain_key=current_issue.chain_key,
        exclude_ulid=current_issue.ulid,
    ):
        _close_issue_silent(
            issue=issue,
            actor_ulid=actor_ulid,
            source_status=SOURCE_STATUS_SUPERSEDED,
            close_reason=f"superseded_by_{superseded_by_reason}",
            admin_status=ADMIN_STATUS_SOURCE_CLOSED,
        )


def _close_issue_silent(
    *,
    issue: LedgerAdminIssue,
    actor_ulid: str | None,
    source_status: str,
    close_reason: str,
    admin_status: str,
) -> None:
    now = now_iso8601_ms()
    issue.source_status = source_status
    issue.resolved_by_actor_ulid = actor_ulid
    issue.closed_at_utc = now
    issue.close_reason = close_reason
    issue.updated_at_utc = now
    close_alert(
        AdminAlertCloseDTO(
            source_slice="ledger",
            reason_code=issue.reason_code,
            request_id=issue.request_id,
            target_ulid=issue.target_ulid,
            source_status=source_status,
            close_reason=close_reason,
            admin_status=admin_status,
            closed_at_utc=now,
        )
    )
    db.session.flush()


def _get_open_issue(
    *,
    request_id: str,
    target_ulid: str | None,
    reason_code: str,
    chain_key: str | None,
) -> LedgerAdminIssue | None:
    stmt = (
        select(LedgerAdminIssue)
        .where(
            LedgerAdminIssue.request_id == request_id,
            LedgerAdminIssue.target_ulid == target_ulid,
            LedgerAdminIssue.reason_code == reason_code,
            LedgerAdminIssue.closed_at_utc.is_(None),
        )
        .order_by(LedgerAdminIssue.created_at_utc.desc())
        .limit(1)
    )
    stmt = _where_chain_key(stmt, chain_key)
    return db.session.execute(stmt).scalar_one_or_none()


def _get_open_hashchain_issue(
    *,
    chain_key: str | None,
    reason_code: str,
) -> LedgerAdminIssue | None:
    stmt = (
        select(LedgerAdminIssue)
        .where(
            LedgerAdminIssue.reason_code == reason_code,
            LedgerAdminIssue.closed_at_utc.is_(None),
        )
        .order_by(LedgerAdminIssue.created_at_utc.desc())
        .limit(1)
    )
    stmt = _where_chain_key(stmt, chain_key)
    return db.session.execute(stmt).scalar_one_or_none()


def _get_open_hashchain_issues(
    *,
    chain_key: str | None,
    exclude_ulid: str | None = None,
) -> list[LedgerAdminIssue]:
    stmt = select(LedgerAdminIssue).where(
        LedgerAdminIssue.reason_code.in_(HASHCHAIN_ATTENTION_REASONS),
        LedgerAdminIssue.closed_at_utc.is_(None),
    )
    stmt = _where_chain_key(stmt, chain_key)
    if exclude_ulid:
        stmt = stmt.where(LedgerAdminIssue.ulid != exclude_ulid)
    stmt = stmt.order_by(LedgerAdminIssue.created_at_utc.asc())
    return list(db.session.execute(stmt).scalars())


def _where_chain_key(stmt, chain_key: str | None):
    if chain_key is None:
        return stmt.where(LedgerAdminIssue.chain_key.is_(None))
    return stmt.where(LedgerAdminIssue.chain_key == chain_key)


def _create_issue(
    *,
    reason_code: str,
    request_id: str,
    target_ulid: str | None,
    chain_key: str | None,
    event_ulid: str | None,
    actor_ulid: str | None,
    title: str,
    summary: str,
    context: dict[str, Any] | None,
    source_status: str,
) -> LedgerAdminIssue:
    now = now_iso8601_ms()
    issue = LedgerAdminIssue(
        reason_code=reason_code,
        source_status=source_status,
        request_id=request_id,
        target_ulid=target_ulid,
        chain_key=chain_key,
        event_ulid=event_ulid,
        requested_by_actor_ulid=actor_ulid,
        resolved_by_actor_ulid=None,
        title=title,
        summary=summary,
        details_json=dict(context or {}),
        closed_at_utc=None,
        close_reason=None,
        created_at_utc=now,
        updated_at_utc=now,
    )
    db.session.add(issue)
    db.session.flush()
    return issue


def _get_issue_or_raise(issue_ulid: str) -> LedgerAdminIssue:
    issue = db.session.get(LedgerAdminIssue, issue_ulid)
    if not issue:
        raise LookupError(f"Ledger admin issue not found: {issue_ulid}")
    return issue


def _upsert_admin_alert(issue: LedgerAdminIssue) -> AdminAlertReceiptDTO:
    return upsert_alert(
        AdminAlertUpsertDTO(
            source_slice="ledger",
            reason_code=issue.reason_code,
            request_id=issue.request_id,
            target_ulid=issue.target_ulid,
            title=issue.title,
            summary=issue.summary,
            source_status=issue.source_status,
            workflow_key=WORKFLOW_KEY,
            resolution_target=AdminResolutionTargetDTO(
                route_name="ledger.admin_issue_get",
                route_params={"issue_ulid": issue.ulid},
                launch_label="Open Ledger hash-chain issue",
            ),
            context=_alert_context(issue),
        )
    )


def _alert_context(issue: LedgerAdminIssue) -> dict[str, Any]:
    details = dict(issue.details_json or {})
    return {
        "issue_ulid": issue.ulid,
        "reason_code": issue.reason_code,
        "source_status": issue.source_status,
        "chain_key": issue.chain_key,
        "event_ulid": issue.event_ulid or _first_failure_event_ulid(details),
        "check_ulid": _latest_detail_check_ulid(details),
        "last_repair_ulid": _latest_detail_repair_ulid(details),
        "routine_backup_allowed": details.get("routine_backup_allowed"),
        "dirty_forensic_backup_only": details.get(
            "dirty_forensic_backup_only"
        ),
        "broken": details.get("broken"),
    }


def _backup_posture(issue: LedgerAdminIssue) -> dict[str, Any]:
    details = dict(issue.details_json or {})
    return {
        "routine_backup_allowed": bool(
            details.get("routine_backup_allowed", False)
        ),
        "dirty_forensic_backup_only": bool(
            details.get("dirty_forensic_backup_only", False)
        ),
        "check_ulid": details.get("check_ulid"),
    }


def _allowed_actions(issue: LedgerAdminIssue) -> tuple[str, ...]:
    if issue.closed_at_utc:
        return ()
    actions = ["run_verify"]
    if issue.chain_key and issue.reason_code in HASHCHAIN_ATTENTION_REASONS:
        actions.append("repair_hashchain")
    actions.extend(["close_restored", "close_no_repair"])
    return tuple(actions)


def _clean_issue_view(view: str | None) -> str:
    clean = str(view or "active").strip().lower()
    if clean in {"active", "closed", "all"}:
        return clean
    return "active"


def _list_issues(
    *,
    view: str,
    limit: int,
) -> list[LedgerAdminIssue]:
    stmt = select(LedgerAdminIssue)
    if view == "active":
        stmt = stmt.where(LedgerAdminIssue.closed_at_utc.is_(None))
    elif view == "closed":
        stmt = stmt.where(LedgerAdminIssue.closed_at_utc.is_not(None))

    stmt = stmt.order_by(desc(LedgerAdminIssue.updated_at_utc)).limit(limit)
    return list(db.session.execute(stmt).scalars())


def _list_checks(
    *,
    issue_ulid: str | None = None,
    limit: int = 20,
) -> list[LedgerHashchainCheck]:
    stmt = select(LedgerHashchainCheck)
    if issue_ulid:
        stmt = stmt.where(LedgerHashchainCheck.issue_ulid == issue_ulid)
    stmt = stmt.order_by(desc(LedgerHashchainCheck.created_at_utc)).limit(
        limit
    )
    return list(db.session.execute(stmt).scalars())


def _list_repairs(
    *,
    issue_ulid: str | None = None,
    limit: int = 20,
) -> list[LedgerHashchainRepair]:
    stmt = select(LedgerHashchainRepair)
    if issue_ulid:
        stmt = stmt.where(LedgerHashchainRepair.issue_ulid == issue_ulid)
    stmt = stmt.order_by(desc(LedgerHashchainRepair.created_at_utc)).limit(
        limit
    )
    return list(db.session.execute(stmt).scalars())


def _list_repairs_for_check(
    check_ulid: str,
) -> list[LedgerHashchainRepair]:
    stmt = (
        select(LedgerHashchainRepair)
        .where(
            or_(
                LedgerHashchainRepair.source_check_ulid == check_ulid,
                LedgerHashchainRepair.post_repair_check_ulid == check_ulid,
            )
        )
        .order_by(desc(LedgerHashchainRepair.created_at_utc))
    )
    return list(db.session.execute(stmt).scalars())


def _issue_index_row(issue: LedgerAdminIssue) -> dict[str, Any]:
    details = dict(issue.details_json or {})
    return {
        "issue_ulid": issue.ulid,
        "title": issue.title,
        "reason_code": issue.reason_code,
        "source_status": issue.source_status,
        "chain_key": issue.chain_key,
        "event_ulid": issue.event_ulid or _first_failure_event_ulid(details),
        "request_id": issue.request_id,
        "closed_at_utc": issue.closed_at_utc,
        "updated_at_utc": issue.updated_at_utc,
        "last_verify_check_ulid": _latest_detail_check_ulid(details),
        "last_repair_ulid": _latest_detail_repair_ulid(details),
    }


def _check_index_row(check: LedgerHashchainCheck) -> dict[str, Any]:
    return {
        "check_ulid": check.ulid,
        "issue_ulid": check.issue_ulid,
        "check_kind": check.check_kind,
        "reason_code": check.reason_code,
        "source_status": check.source_status,
        "chain_key": check.chain_key,
        "completed_at_utc": check.completed_at_utc,
        "ok": bool(check.ok),
        "checked_count": check.checked_count,
        "anomaly_count": check.anomaly_count,
        "failure_count": check.failure_count,
        "routine_backup_allowed": bool(check.routine_backup_allowed),
        "dirty_forensic_backup_only": bool(check.dirty_forensic_backup_only),
    }


def _repair_index_row(repair: LedgerHashchainRepair) -> dict[str, Any]:
    return {
        "repair_ulid": repair.ulid,
        "issue_ulid": repair.issue_ulid,
        "repair_kind": repair.repair_kind,
        "reason_code": repair.reason_code,
        "source_status": repair.source_status,
        "chain_key": repair.chain_key,
        "completed_at_utc": repair.completed_at_utc,
        "source_check_ulid": repair.source_check_ulid,
        "post_repair_check_ulid": repair.post_repair_check_ulid,
        "affected_count": len(repair.affected_event_ulids_json or ()),
    }


def _get_issue_optional(issue_ulid: str | None) -> LedgerAdminIssue | None:
    if not issue_ulid:
        return None
    return db.session.get(LedgerAdminIssue, issue_ulid)


def _get_check_or_raise(check_ulid: str) -> LedgerHashchainCheck:
    row = db.session.get(LedgerHashchainCheck, check_ulid)
    if row is None:
        raise LookupError(f"Ledger hashchain check not found: {check_ulid}")
    return row


def _get_repair_or_raise(repair_ulid: str) -> LedgerHashchainRepair:
    row = db.session.get(LedgerHashchainRepair, repair_ulid)
    if row is None:
        raise LookupError(f"Ledger hashchain repair not found: {repair_ulid}")
    return row


def _latest_detail_check_ulid(
    details: dict[str, Any] | None,
) -> str | None:
    if not isinstance(details, dict):
        return None
    last_verify = details.get("last_verify") or {}
    if isinstance(last_verify, dict):
        value = str(last_verify.get("check_ulid") or "").strip()
        if value:
            return value
    value = str(details.get("check_ulid") or "").strip()
    return value or None


def _latest_detail_repair_ulid(
    details: dict[str, Any] | None,
) -> str | None:
    if not isinstance(details, dict):
        return None
    last_repair = details.get("last_repair") or {}
    if isinstance(last_repair, dict):
        value = str(last_repair.get("repair_ulid") or "").strip()
        if value:
            return value
    return None
