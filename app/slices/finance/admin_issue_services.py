# app/slices/finance/admin_issue_services.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts import admin_v2
from app.extensions.contracts.admin_v2 import (
    AdminAlertCloseDTO,
    AdminAlertUpsertDTO,
    AdminResolutionTargetDTO,
)
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import FinanceAdminIssue

SOURCE_SLICE = "finance"

ISSUE_STATUS_OPEN = "open"
ISSUE_STATUS_IN_REVIEW = "in_review"
ISSUE_STATUS_RESOLVED = "resolved"
ISSUE_STATUS_FALSE_POSITIVE = "false_positive"
ISSUE_STATUS_MANUAL_RESOLUTION_REQUIRED = "manual_resolution_required"

TERMINAL_ISSUE_STATUSES = {
    ISSUE_STATUS_RESOLVED,
    ISSUE_STATUS_FALSE_POSITIVE,
    ISSUE_STATUS_MANUAL_RESOLUTION_REQUIRED,
}


@dataclass(frozen=True)
class FinanceAdminIssueView:
    """PII-free view of a Finance-owned Admin issue.

    Admin may display and launch this issue, but Finance owns the truth,
    mutation, review evidence, and resolution mechanics.
    """

    issue_ulid: str
    reason_code: str
    source_status: str
    issue_status: str
    workflow_key: str
    target_ulid: str | None
    request_id: str
    title: str
    summary: str
    detection: dict[str, Any]
    preview: dict[str, Any]
    resolution: dict[str, Any]
    opened_at_utc: str
    review_started_at_utc: str | None
    review_started_by_actor_ulid: str | None
    resolved_at_utc: str | None
    resolved_by_actor_ulid: str | None
    close_reason: str | None
    admin_alert_ulid: str | None


def _now() -> str:
    return now_iso8601_ms()


def _dedupe_key(
    *,
    reason_code: str,
    request_id: str,
    target_ulid: str | None,
) -> str:
    target = target_ulid or "~"
    return f"{SOURCE_SLICE}:{reason_code}:{request_id}:{target}"


def _to_view(row: FinanceAdminIssue) -> FinanceAdminIssueView:
    return FinanceAdminIssueView(
        issue_ulid=row.ulid,
        reason_code=row.reason_code,
        source_status=row.source_status,
        issue_status=row.issue_status,
        workflow_key=row.workflow_key,
        target_ulid=row.target_ulid,
        request_id=row.request_id,
        title=row.title,
        summary=row.summary,
        detection=dict(row.detection_json or {}),
        preview=dict(row.preview_json or {}),
        resolution=dict(row.resolution_json or {}),
        opened_at_utc=row.opened_at_utc,
        review_started_at_utc=row.review_started_at_utc,
        review_started_by_actor_ulid=row.review_started_by_actor_ulid,
        resolved_at_utc=row.resolved_at_utc,
        resolved_by_actor_ulid=row.resolved_by_actor_ulid,
        close_reason=row.close_reason,
        admin_alert_ulid=row.admin_alert_ulid,
    )


def _get_issue_row(issue_ulid: str) -> FinanceAdminIssue:
    row = db.session.get(FinanceAdminIssue, issue_ulid)
    if row is None:
        raise LookupError(f"Finance admin issue not found: {issue_ulid}")
    return row


def _normalize_json(value: dict[str, Any] | None) -> dict[str, object]:
    if not value:
        return {}
    return dict(value)


def _finding_to_json(finding: object) -> dict[str, object]:
    """Convert scanner finding dataclasses to JSON-safe evidence."""

    return {
        "code": str(getattr(finding, "code", "")),
        "message": str(getattr(finding, "message", "")),
        "severity": str(getattr(finding, "severity", "")),
        "journal_ulid": getattr(finding, "journal_ulid", None),
        "journal_line_ulid": getattr(finding, "journal_line_ulid", None),
        "context": dict(getattr(finding, "context", {}) or {}),
    }


def _scan_detection(scan_result: object) -> dict[str, object]:
    """Create compact PII-free detection evidence from a scan result."""

    findings = tuple(getattr(scan_result, "findings", ()) or ())
    return {
        "reason_code": str(getattr(scan_result, "reason_code", "")),
        "source_status": str(getattr(scan_result, "source_status", "")),
        "finding_count": int(getattr(scan_result, "finding_count", 0) or 0),
        "blocks_finance_projection": bool(
            getattr(scan_result, "blocks_finance_projection", False)
        ),
        "findings": [_finding_to_json(finding) for finding in findings],
    }


def _admin_context(row: FinanceAdminIssue) -> dict[str, object]:
    return {
        "issue_ulid": row.ulid,
        "reason_code": row.reason_code,
        "source_status": row.source_status,
        "issue_status": row.issue_status,
        "workflow_key": row.workflow_key,
        "finding_count": int(
            dict(row.detection_json or {}).get("finding_count") or 0
        ),
    }


def _resolution_target(row: FinanceAdminIssue) -> AdminResolutionTargetDTO:
    """Return the future Finance-owned launch target.

    The route is added in the next phase. Admin stores the target now; if the
    route does not exist yet, Admin's display layer should simply be unable to
    render a launch href until routes are registered.
    """

    return AdminResolutionTargetDTO(
        route_name="finance.admin_issue_detail",
        route_params={"issue_ulid": row.ulid},
        launch_label="Open Finance issue",
        http_method="GET",
    )


def _upsert_admin_alert(row: FinanceAdminIssue) -> str | None:
    receipt = admin_v2.upsert_alert(
        AdminAlertUpsertDTO(
            source_slice=SOURCE_SLICE,
            reason_code=row.reason_code,
            request_id=row.request_id,
            target_ulid=row.target_ulid,
            title=row.title,
            summary=row.summary,
            source_status=row.source_status,
            workflow_key=row.workflow_key,
            resolution_target=_resolution_target(row),
            context=_admin_context(row),
        )
    )
    return receipt.alert_ulid


def _close_admin_alert(
    row: FinanceAdminIssue,
    *,
    close_reason: str,
) -> None:
    admin_v2.close_alert(
        AdminAlertCloseDTO(
            source_slice=SOURCE_SLICE,
            reason_code=row.reason_code,
            request_id=row.request_id,
            target_ulid=row.target_ulid,
            source_status=row.source_status,
            close_reason=close_reason,
            admin_status="source_closed",
            closed_at_utc=row.resolved_at_utc,
        )
    )


def _emit_issue_event(
    *,
    operation: str,
    row: FinanceAdminIssue,
    actor_ulid: str | None,
    meta: dict[str, Any] | None = None,
) -> None:
    event_bus.emit(
        domain="finance",
        operation=operation,
        request_id=row.request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        refs={
            "issue_ulid": row.ulid,
            "reason_code": row.reason_code,
            "target_ulid": row.target_ulid,
            "admin_alert_ulid": row.admin_alert_ulid,
        },
        changed={
            "source_status": row.source_status,
            "issue_status": row.issue_status,
        },
        meta=dict(meta or {}),
        chain_key="finance.admin_issue",
    )


def raise_integrity_admin_issue(
    *,
    reason_code: str,
    request_id: str,
    title: str,
    summary: str,
    detection: dict[str, Any],
    workflow_key: str,
    target_ulid: str | None = None,
    source_status: str = "open",
    actor_ulid: str | None = None,
) -> FinanceAdminIssueView:
    """Create or refresh a Finance-owned Admin issue.

    Canon note for Future Dev:
      This is Finance truth. Admin gets a cue card through admin_v2, but Admin
      must not become the owner of Finance diagnostics or Finance repair.
    """

    now = _now()
    key = _dedupe_key(
        reason_code=reason_code,
        request_id=request_id,
        target_ulid=target_ulid,
    )

    row = db.session.execute(
        select(FinanceAdminIssue).where(FinanceAdminIssue.dedupe_key == key)
    ).scalar_one_or_none()

    if row is None:
        row = FinanceAdminIssue(
            reason_code=reason_code,
            source_status=source_status,
            issue_status=ISSUE_STATUS_OPEN,
            workflow_key=workflow_key,
            target_ulid=target_ulid,
            request_id=request_id,
            title=title,
            summary=summary,
            detection_json=_normalize_json(detection),
            preview_json={},
            resolution_json={},
            opened_at_utc=now,
            review_started_at_utc=None,
            review_started_by_actor_ulid=None,
            resolved_at_utc=None,
            resolved_by_actor_ulid=None,
            close_reason=None,
            admin_alert_ulid=None,
            dedupe_key=key,
        )
        db.session.add(row)
        created = True
    else:
        row.reason_code = reason_code
        row.source_status = source_status
        row.issue_status = ISSUE_STATUS_OPEN
        row.workflow_key = workflow_key
        row.target_ulid = target_ulid
        row.title = title
        row.summary = summary
        row.detection_json = _normalize_json(detection)
        row.resolved_at_utc = None
        row.resolved_by_actor_ulid = None
        row.close_reason = None
        created = False

    db.session.flush()
    row.admin_alert_ulid = _upsert_admin_alert(row)
    db.session.flush()

    _emit_issue_event(
        operation="admin_issue_raised",
        row=row,
        actor_ulid=actor_ulid,
        meta={"created": created},
    )
    return _to_view(row)


def integrity_review_get(issue_ulid: str) -> FinanceAdminIssueView:
    return _to_view(_get_issue_row(issue_ulid))


def list_integrity_admin_issues(
    *,
    view: str = "active",
) -> tuple[FinanceAdminIssueView, ...]:
    """List Finance-owned Admin issues for Admin/Auditor drill-down.

    The Admin slice owns queue posture. Finance owns this slice-local
    issue evidence and resolution state. This list is intentionally useful
    for both Admin Dashboard launch paths and the future read-only Auditor
    Dashboard.
    """
    view = str(view or "active").strip().lower()
    stmt = select(FinanceAdminIssue)

    if view == "active":
        stmt = stmt.where(
            FinanceAdminIssue.issue_status.not_in(
                sorted(TERMINAL_ISSUE_STATUSES)
            )
        )
    elif view == "closed":
        stmt = stmt.where(
            FinanceAdminIssue.issue_status.in_(
                sorted(TERMINAL_ISSUE_STATUSES)
            )
        )
    elif view != "all":
        stmt = stmt.where(FinanceAdminIssue.issue_status == view)

    stmt = stmt.order_by(
        FinanceAdminIssue.updated_at_utc.desc(),
        FinanceAdminIssue.ulid.desc(),
    )
    return tuple(_to_view(row) for row in db.session.execute(stmt).scalars())


def start_integrity_review(
    issue_ulid: str,
    *,
    actor_ulid: str,
) -> FinanceAdminIssueView:
    row = _get_issue_row(issue_ulid)
    if row.issue_status in TERMINAL_ISSUE_STATUSES:
        raise ValueError("Cannot start review for a terminal Finance issue")

    now = _now()
    row.issue_status = ISSUE_STATUS_IN_REVIEW
    row.source_status = "in_review"
    row.review_started_at_utc = now
    row.review_started_by_actor_ulid = actor_ulid
    db.session.flush()

    if row.admin_alert_ulid:
        admin_v2.set_alert_status(
            row.admin_alert_ulid,
            admin_status="in_review",
        )

    _emit_issue_event(
        operation="admin_issue_review_started",
        row=row,
        actor_ulid=actor_ulid,
    )
    return _to_view(row)


def close_integrity_admin_issue(
    issue_ulid: str,
    *,
    actor_ulid: str,
    close_reason: str,
    issue_status: str = ISSUE_STATUS_RESOLVED,
    resolution: dict[str, Any] | None = None,
) -> FinanceAdminIssueView:
    row = _get_issue_row(issue_ulid)
    if issue_status not in TERMINAL_ISSUE_STATUSES:
        raise ValueError("Finance issue close requires a terminal status")

    now = _now()
    row.issue_status = issue_status
    row.source_status = "closed"
    row.resolved_at_utc = now
    row.resolved_by_actor_ulid = actor_ulid
    row.close_reason = close_reason
    row.resolution_json = _normalize_json(resolution)
    db.session.flush()

    _close_admin_alert(row, close_reason=close_reason)
    _emit_issue_event(
        operation="admin_issue_closed",
        row=row,
        actor_ulid=actor_ulid,
        meta={"close_reason": close_reason},
    )
    return _to_view(row)


def _raise_from_scan(
    *,
    scan_result: object,
    request_id: str,
    title: str,
    summary: str,
    workflow_key: str,
    target_ulid: str | None = None,
    actor_ulid: str | None = None,
) -> FinanceAdminIssueView:
    return raise_integrity_admin_issue(
        reason_code=str(getattr(scan_result, "reason_code")),
        request_id=request_id,
        title=title,
        summary=summary,
        detection=_scan_detection(scan_result),
        workflow_key=workflow_key,
        target_ulid=target_ulid,
        source_status=str(getattr(scan_result, "source_status")),
        actor_ulid=actor_ulid,
    )


def raise_journal_integrity_admin_issue(
    *,
    scan_result: object,
    request_id: str,
    actor_ulid: str | None = None,
) -> FinanceAdminIssueView:
    return _raise_from_scan(
        scan_result=scan_result,
        request_id=request_id,
        title="Finance journal integrity failure",
        summary=(
            "Finance detected a Journal/JournalLine integrity failure. "
            "Staff-facing financial projection must remain blocked until "
            "Finance resolves or classifies this issue."
        ),
        workflow_key="finance.journal_integrity",
        actor_ulid=actor_ulid,
    )


def raise_balance_projection_drift_admin_issue(
    *,
    scan_result: object,
    request_id: str,
    actor_ulid: str | None = None,
) -> FinanceAdminIssueView:
    return _raise_from_scan(
        scan_result=scan_result,
        request_id=request_id,
        title="Finance balance projection drift",
        summary=(
            "Finance detected BalanceMonthly drift from JournalLine truth. "
            "Projection rebuild preview should be reviewed before repair."
        ),
        workflow_key="finance.balance_projection",
        actor_ulid=actor_ulid,
    )


def raise_posting_fact_drift_admin_issue(
    *,
    scan_result: object,
    request_id: str,
    actor_ulid: str | None = None,
) -> FinanceAdminIssueView:
    return _raise_from_scan(
        scan_result=scan_result,
        request_id=request_id,
        title="Finance semantic posting fact drift",
        summary=(
            "Finance detected semantic posting fact drift. Calendar "
            "staff-facing money posture may be unsafe for affected scope."
        ),
        workflow_key="finance.posting_fact",
        actor_ulid=actor_ulid,
    )


def raise_control_state_drift_admin_issue(
    *,
    scan_result: object,
    request_id: str,
    actor_ulid: str | None = None,
) -> FinanceAdminIssueView:
    return _raise_from_scan(
        scan_result=scan_result,
        request_id=request_id,
        title="Finance control-state drift",
        summary=(
            "Finance detected Reserve or Encumbrance control-state drift. "
            "Affected funding demand posture may require review."
        ),
        workflow_key="finance.control_state",
        actor_ulid=actor_ulid,
    )


def raise_ops_float_sanity_admin_issue(
    *,
    scan_result: object,
    request_id: str,
    actor_ulid: str | None = None,
) -> FinanceAdminIssueView:
    return _raise_from_scan(
        scan_result=scan_result,
        request_id=request_id,
        title="Finance ops-float sanity issue",
        summary=(
            "Finance detected OpsFloat support-state drift. Affected bridge "
            "support posture may require review."
        ),
        workflow_key="finance.ops_float",
        actor_ulid=actor_ulid,
    )


__all__ = [
    "FinanceAdminIssueView",
    "ISSUE_STATUS_OPEN",
    "ISSUE_STATUS_IN_REVIEW",
    "ISSUE_STATUS_RESOLVED",
    "ISSUE_STATUS_FALSE_POSITIVE",
    "ISSUE_STATUS_MANUAL_RESOLUTION_REQUIRED",
    "raise_integrity_admin_issue",
    "list_integrity_admin_issues",
    "integrity_review_get",
    "start_integrity_review",
    "close_integrity_admin_issue",
    "raise_journal_integrity_admin_issue",
    "raise_balance_projection_drift_admin_issue",
    "raise_posting_fact_drift_admin_issue",
    "raise_control_state_drift_admin_issue",
    "raise_ops_float_sanity_admin_issue",
]
