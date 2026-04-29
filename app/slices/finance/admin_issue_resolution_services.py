# app/slices/finance/admin_issue_resolution_services.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.extensions import db, event_bus
from app.extensions.contracts import admin_v2
from app.lib.chrono import now_iso8601_ms
from app.slices.finance import quarantine_services as quarantine_svc
from app.slices.finance.admin_issue_services import (
    ISSUE_STATUS_FALSE_POSITIVE,
    ISSUE_STATUS_IN_REVIEW,
    ISSUE_STATUS_RESOLVED,
    close_integrity_admin_issue,
)
from app.slices.finance.models import FinanceAdminIssue
from app.slices.finance.services_integrity import (
    JOURNAL_INTEGRITY_REASON,
    journal_integrity_scan,
)

JOURNAL_QUARANTINE_MESSAGE = (
    "Finance found a Journal integrity failure. Staff-facing financial "
    "projection is blocked until Finance classifies or resolves this issue."
)


@dataclass(frozen=True)
class JournalIntegrityResolutionResult:
    issue_ulid: str
    action: str
    issue_closed: bool
    active_quarantine_count: int
    resolution_json: dict[str, Any]


def _now() -> str:
    return now_iso8601_ms()


def _get_issue(issue_ulid: str) -> FinanceAdminIssue:
    row = db.session.get(FinanceAdminIssue, issue_ulid)
    if row is None:
        raise LookupError(f"Finance admin issue not found: {issue_ulid}")
    return row


def _require_journal_issue(row: FinanceAdminIssue) -> None:
    if row.reason_code != JOURNAL_INTEGRITY_REASON:
        raise ValueError(
            "Journal integrity workflow requires a "
            f"{JOURNAL_INTEGRITY_REASON} issue"
        )


def _active_quarantines_for_issue(
    issue_ulid: str,
) -> tuple[quarantine_svc.FinanceQuarantineView, ...]:
    quarantines = quarantine_svc.list_quarantines_for_issue(issue_ulid)
    return tuple(
        row
        for row in quarantines
        if row.status == quarantine_svc.STATUS_ACTIVE
    )


def _set_alert_in_review(row: FinanceAdminIssue) -> None:
    if row.admin_alert_ulid:
        admin_v2.set_alert_status(
            row.admin_alert_ulid,
            admin_status="in_review",
        )


def _ensure_review_started(
    row: FinanceAdminIssue,
    *,
    actor_ulid: str,
) -> None:
    if not row.review_started_at_utc:
        row.review_started_at_utc = _now()
    if not row.review_started_by_actor_ulid:
        row.review_started_by_actor_ulid = actor_ulid


def _resolution_state(row: FinanceAdminIssue) -> dict[str, Any]:
    state = dict(row.resolution_json or {})
    history = list(state.get("history") or [])
    state["history"] = history
    state.setdefault("kind", "journal_integrity_resolution")
    state.setdefault(
        "operator_guidance",
        {
            "what_finance_can_do": (
                "Finance can detect and quarantine Journal integrity "
                "problems, but it cannot safely rewrite Journal truth "
                "automatically."
            ),
            "safe_next_steps": [
                "confirm_still_blocked",
                "manual_accounting_review_required",
                "reversal_or_adjustment_required",
                "false_positive_after_clean_rescan",
                "close_after_clean_rescan",
            ],
        },
    )
    return state


def _append_resolution(
    row: FinanceAdminIssue,
    *,
    action: str,
    actor_ulid: str,
    note: str | None,
    recommended_path: str,
    rescan_ok: bool | None = None,
    rescan_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = _now()
    state = _resolution_state(row)
    history = list(state.get("history") or [])

    entry: dict[str, Any] = {
        "action": action,
        "at_utc": now,
        "actor_ulid": actor_ulid,
        "note": note or None,
        "recommended_path": recommended_path,
    }
    if rescan_ok is not None:
        entry["rescan_ok"] = bool(rescan_ok)
        entry["rescan_findings"] = list(rescan_findings or [])

    history.append(entry)

    state.update(
        {
            "kind": "journal_integrity_resolution",
            "updated_at_utc": now,
            "last_action": action,
            "recommended_path": recommended_path,
            "rescan_ok": rescan_ok,
            "rescan_findings": list(rescan_findings or []),
            "history": history,
        }
    )
    return state


def _refresh_issue_quarantines_or_default(
    row: FinanceAdminIssue,
    *,
    actor_ulid: str,
    notes: dict[str, Any] | None = None,
) -> int:
    active = _active_quarantines_for_issue(row.ulid)
    if not active:
        quarantine_svc.open_or_refresh_quarantine(
            source_issue_ulid=row.ulid,
            scope_type=quarantine_svc.SCOPE_GLOBAL,
            scope_ulid=None,
            scope_label="Finance projection",
            posture=quarantine_svc.POSTURE_PROJECTION_BLOCKED,
            message=JOURNAL_QUARANTINE_MESSAGE,
            notes=dict(notes or {}),
            actor_ulid=actor_ulid,
        )
        return len(_active_quarantines_for_issue(row.ulid))

    for existing in active:
        merged_notes = dict(existing.notes or {})
        merged_notes.update(dict(notes or {}))
        quarantine_svc.open_or_refresh_quarantine(
            source_issue_ulid=row.ulid,
            scope_type=existing.scope_type,
            scope_ulid=existing.scope_ulid,
            scope_label=existing.scope_label,
            posture=existing.posture,
            message=existing.message,
            notes=merged_notes,
            actor_ulid=actor_ulid,
        )

    return len(_active_quarantines_for_issue(row.ulid))


def _emit_event(
    *,
    operation: str,
    row: FinanceAdminIssue,
    actor_ulid: str,
    resolution: dict[str, Any],
    active_quarantine_count: int,
) -> None:
    event_bus.emit(
        domain="finance",
        operation=operation,
        request_id=row.request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        refs={
            "issue_ulid": row.ulid,
            "admin_alert_ulid": row.admin_alert_ulid,
        },
        changed={
            "issue_status": row.issue_status,
            "source_status": row.source_status,
            "active_quarantine_count": active_quarantine_count,
            "last_action": resolution.get("last_action"),
        },
        meta={
            "reason_code": row.reason_code,
            "recommended_path": resolution.get("recommended_path"),
        },
        chain_key="finance.journal_integrity",
    )


def _dirty_rescan_findings() -> list[dict[str, Any]]:
    result = journal_integrity_scan()
    findings: list[dict[str, Any]] = []
    for finding in result.findings:
        findings.append(
            {
                "code": finding.code,
                "message": finding.message,
                "severity": finding.severity,
                "journal_ulid": finding.journal_ulid,
                "journal_line_ulid": finding.journal_line_ulid,
                "context": dict(finding.context or {}),
            }
        )
    return findings


def confirm_journal_integrity_still_blocked(
    issue_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> JournalIntegrityResolutionResult:
    row = _get_issue(issue_ulid)
    _require_journal_issue(row)

    row.issue_status = ISSUE_STATUS_IN_REVIEW
    row.source_status = "open"
    _ensure_review_started(row, actor_ulid=actor_ulid)
    _set_alert_in_review(row)

    resolution = _append_resolution(
        row,
        action="confirm_still_blocked",
        actor_ulid=actor_ulid,
        note=note,
        recommended_path="containment_and_review",
    )
    row.resolution_json = resolution
    db.session.flush()

    quarantine_count = _refresh_issue_quarantines_or_default(
        row,
        actor_ulid=actor_ulid,
        notes={"recommended_path": "containment_and_review"},
    )
    _emit_event(
        operation="journal_integrity_block_confirmed",
        row=row,
        actor_ulid=actor_ulid,
        resolution=resolution,
        active_quarantine_count=quarantine_count,
    )
    return JournalIntegrityResolutionResult(
        issue_ulid=row.ulid,
        action="confirm_still_blocked",
        issue_closed=False,
        active_quarantine_count=quarantine_count,
        resolution_json=resolution,
    )


def mark_journal_integrity_manual_review_required(
    issue_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> JournalIntegrityResolutionResult:
    row = _get_issue(issue_ulid)
    _require_journal_issue(row)

    row.issue_status = ISSUE_STATUS_IN_REVIEW
    row.source_status = "open"
    _ensure_review_started(row, actor_ulid=actor_ulid)
    _set_alert_in_review(row)

    resolution = _append_resolution(
        row,
        action="manual_accounting_review_required",
        actor_ulid=actor_ulid,
        note=note,
        recommended_path="manual_accounting_review",
    )
    row.resolution_json = resolution
    db.session.flush()

    quarantine_count = _refresh_issue_quarantines_or_default(
        row,
        actor_ulid=actor_ulid,
        notes={"recommended_path": "manual_accounting_review"},
    )
    _emit_event(
        operation="journal_integrity_manual_review_required",
        row=row,
        actor_ulid=actor_ulid,
        resolution=resolution,
        active_quarantine_count=quarantine_count,
    )
    return JournalIntegrityResolutionResult(
        issue_ulid=row.ulid,
        action="manual_accounting_review_required",
        issue_closed=False,
        active_quarantine_count=quarantine_count,
        resolution_json=resolution,
    )


def mark_journal_integrity_reversal_required(
    issue_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> JournalIntegrityResolutionResult:
    row = _get_issue(issue_ulid)
    _require_journal_issue(row)

    row.issue_status = ISSUE_STATUS_IN_REVIEW
    row.source_status = "open"
    _ensure_review_started(row, actor_ulid=actor_ulid)
    _set_alert_in_review(row)

    resolution = _append_resolution(
        row,
        action="reversal_or_adjustment_required",
        actor_ulid=actor_ulid,
        note=note,
        recommended_path="reversal_or_adjustment_required",
    )
    row.resolution_json = resolution
    db.session.flush()

    quarantine_count = _refresh_issue_quarantines_or_default(
        row,
        actor_ulid=actor_ulid,
        notes={"recommended_path": "reversal_or_adjustment_required"},
    )
    _emit_event(
        operation="journal_integrity_reversal_required",
        row=row,
        actor_ulid=actor_ulid,
        resolution=resolution,
        active_quarantine_count=quarantine_count,
    )
    return JournalIntegrityResolutionResult(
        issue_ulid=row.ulid,
        action="reversal_or_adjustment_required",
        issue_closed=False,
        active_quarantine_count=quarantine_count,
        resolution_json=resolution,
    )


def mark_journal_integrity_false_positive_after_clean_rescan(
    issue_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> JournalIntegrityResolutionResult:
    row = _get_issue(issue_ulid)
    _require_journal_issue(row)

    findings = _dirty_rescan_findings()
    if findings:
        raise ValueError(
            "Journal integrity rescan is still dirty; cannot mark false positive"
        )

    resolution = _append_resolution(
        row,
        action="false_positive_after_clean_rescan",
        actor_ulid=actor_ulid,
        note=note,
        recommended_path="false_positive",
        rescan_ok=True,
        rescan_findings=[],
    )

    active_quarantines = _active_quarantines_for_issue(row.ulid)
    close_integrity_admin_issue(
        row.ulid,
        actor_ulid=actor_ulid,
        close_reason="journal_integrity_false_positive",
        issue_status=ISSUE_STATUS_FALSE_POSITIVE,
        resolution=resolution,
    )
    for quarantine in active_quarantines:
        quarantine_svc.release_quarantine(
            quarantine.quarantine_ulid,
            actor_ulid=actor_ulid,
            close_reason="journal_integrity_false_positive",
            notes={"rescan_ok": True},
        )

    refreshed = _get_issue(row.ulid)
    _emit_event(
        operation="journal_integrity_false_positive",
        row=refreshed,
        actor_ulid=actor_ulid,
        resolution=resolution,
        active_quarantine_count=0,
    )
    return JournalIntegrityResolutionResult(
        issue_ulid=refreshed.ulid,
        action="false_positive_after_clean_rescan",
        issue_closed=True,
        active_quarantine_count=0,
        resolution_json=resolution,
    )


def close_journal_integrity_after_clean_rescan(
    issue_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> JournalIntegrityResolutionResult:
    row = _get_issue(issue_ulid)
    _require_journal_issue(row)

    findings = _dirty_rescan_findings()
    if findings:
        raise ValueError(
            "Journal integrity rescan is still dirty; cannot close issue"
        )

    resolution = _append_resolution(
        row,
        action="close_after_clean_rescan",
        actor_ulid=actor_ulid,
        note=note,
        recommended_path="resolved_after_external_correction",
        rescan_ok=True,
        rescan_findings=[],
    )

    active_quarantines = _active_quarantines_for_issue(row.ulid)
    close_integrity_admin_issue(
        row.ulid,
        actor_ulid=actor_ulid,
        close_reason="journal_integrity_clean_rescan",
        issue_status=ISSUE_STATUS_RESOLVED,
        resolution=resolution,
    )
    for quarantine in active_quarantines:
        quarantine_svc.release_quarantine(
            quarantine.quarantine_ulid,
            actor_ulid=actor_ulid,
            close_reason="journal_integrity_clean_rescan",
            notes={"rescan_ok": True},
        )

    refreshed = _get_issue(row.ulid)
    _emit_event(
        operation="journal_integrity_closed_after_clean_rescan",
        row=refreshed,
        actor_ulid=actor_ulid,
        resolution=resolution,
        active_quarantine_count=0,
    )
    return JournalIntegrityResolutionResult(
        issue_ulid=refreshed.ulid,
        action="close_after_clean_rescan",
        issue_closed=True,
        active_quarantine_count=0,
        resolution_json=resolution,
    )


__all__ = [
    "JournalIntegrityResolutionResult",
    "confirm_journal_integrity_still_blocked",
    "mark_journal_integrity_manual_review_required",
    "mark_journal_integrity_reversal_required",
    "mark_journal_integrity_false_positive_after_clean_rescan",
    "close_journal_integrity_after_clean_rescan",
]
