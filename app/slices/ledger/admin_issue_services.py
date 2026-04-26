# app/slices/ledger/admin_issue_services.py

from __future__ import annotations

from typing import Any

from sqlalchemy import select

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

from .models import LedgerAdminIssue
from .services import verify_chain

SOURCE_STATUS_OPEN = "open"
SOURCE_STATUS_INVESTIGATING = "investigating"
SOURCE_STATUS_RESTORED = "restored"
SOURCE_STATUS_NO_REPAIR = "closed_no_repair"

ADMIN_STATUS_RESOLVED = "resolved"
ADMIN_STATUS_SOURCE_CLOSED = "source_closed"

WORKFLOW_KEY = "ledger_admin_issue"


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
) -> AdminAlertReceiptDTO:
    """
    Create or refresh Ledger-owned issue truth and cue Admin.

    No commit here. Caller owns the transaction boundary.
    """
    rid = ensure_request_id(request_id)
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
        )
    else:
        issue.title = title
        issue.summary = summary
        issue.event_ulid = event_ulid or issue.event_ulid
        issue.details_json = dict(context or issue.details_json or {})
        issue.updated_at_utc = now_iso8601_ms()
        db.session.flush()

    return _upsert_admin_alert(issue)


def ledger_issue_get(issue_ulid: str) -> dict[str, Any]:
    issue = _get_issue_or_raise(issue_ulid)
    return {
        "title": issue.title,
        "summary": issue.summary,
        "issue_ulid": issue.ulid,
        "reason_code": issue.reason_code,
        "source_status": issue.source_status,
        "request_id": issue.request_id,
        "target_ulid": issue.target_ulid,
        "chain_key": issue.chain_key,
        "event_ulid": issue.event_ulid,
        "details": issue.details_json or {},
        "closed_at_utc": issue.closed_at_utc,
        "close_reason": issue.close_reason,
        "allowed_actions": _allowed_actions(issue),
        "as_of_utc": now_iso8601_ms(),
    }


def run_verify_for_issue(
    *,
    issue_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    """Run verification for the issue chain and refresh issue context."""
    rid = ensure_request_id(request_id)
    issue = _get_issue_or_raise(issue_ulid)
    result = verify_chain(chain_key=issue.chain_key)

    details = dict(issue.details_json or {})
    details["last_verify"] = result
    details["last_verify_at_utc"] = now_iso8601_ms()
    issue.details_json = details
    issue.source_status = (
        SOURCE_STATUS_INVESTIGATING
        if not result.get("ok")
        else issue.source_status
    )
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
        },
        changed={"fields": ["details_json", "source_status"]},
        meta={
            "origin": "ledger_admin_issue",
            "reason_code": issue.reason_code,
            "verify_ok": bool(result.get("ok")),
        },
        happened_at_utc=now_iso8601_ms(),
        chain_key="ledger.health",
    )
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
            LedgerAdminIssue.chain_key == chain_key,
            LedgerAdminIssue.closed_at_utc.is_(None),
        )
        .order_by(LedgerAdminIssue.created_at_utc.desc())
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()


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
) -> LedgerAdminIssue:
    now = now_iso8601_ms()
    issue = LedgerAdminIssue(
        reason_code=reason_code,
        source_status=SOURCE_STATUS_OPEN,
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
                launch_label="Open Ledger issue",
            ),
            context=_alert_context(issue),
        )
    )


def _alert_context(issue: LedgerAdminIssue) -> dict[str, Any]:
    return {
        "issue_ulid": issue.ulid,
        "reason_code": issue.reason_code,
        "chain_key": issue.chain_key,
        "event_ulid": issue.event_ulid,
        "details": issue.details_json or {},
    }


def _allowed_actions(issue: LedgerAdminIssue) -> tuple[str, ...]:
    if issue.closed_at_utc:
        return ()
    return ("run_verify", "close_restored", "close_no_repair")
