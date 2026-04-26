# app/slices/admin/services.py

"""
VCDB v2 — Admin slice services

Admin-local queue composition and operational inbox behavior.

This module may:
- compose Admin read views
- create/update/close Admin inbox rows
- archive terminal inbox rows

This module must not:
- commit or rollback transactions
- emit Ledger events
- own foreign slice semantics
- execute foreign corrective commands
Policy edits work
"""

from __future__ import annotations

from dataclasses import asdict
from flask import url_for
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import (
    auth_v1,
    entity_v2,
    governance_v2,
)
from app.extensions.contracts.admin_v2 import (
    AdminAlertCloseDTO,
    AdminAlertReceiptDTO,
    AdminAlertUpsertDTO,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

from .mapper import (
    AuthOperatorsPageDTO,
    CronPageDTO,
    DashboardDTO,
    InboxItemDTO,
    InboxPageDTO,
    PolicyDetailPageDTO,
    PolicyHealthSummaryDTO,
    PolicyIndexPageDTO,
    PolicyIssueDTO,
    PolicyMetaItemDTO,
    PolicyPreviewPageDTO,
    to_auth_operator_summary,
    to_auth_operators_page,
    to_dashboard,
    to_inbox_item,
    to_inbox_page,
    to_inbox_summary,
    to_policy_detail_page,
    to_policy_health_summary,
    to_policy_index_item,
    to_policy_index_page,
    to_policy_issue,
    to_policy_meta_item,
    to_policy_preview_page,
    to_slice_health_card,
)
from .models import AdminAlert, AdminAlertArchive

# -----------------
# Declared Constants
# -----------------


ADMIN_STATUS_OPEN = "open"
ADMIN_STATUS_ACKNOWLEDGED = "acknowledged"
ADMIN_STATUS_IN_REVIEW = "in_review"
ADMIN_STATUS_SNOOZED = "snoozed"

ADMIN_STATUS_RESOLVED = "resolved"
ADMIN_STATUS_SOURCE_CLOSED = "source_closed"
ADMIN_STATUS_DISMISSED = "dismissed"
ADMIN_STATUS_DUPLICATE = "duplicate"

ACTIVE_ADMIN_STATUSES = {
    ADMIN_STATUS_OPEN,
    ADMIN_STATUS_ACKNOWLEDGED,
    ADMIN_STATUS_IN_REVIEW,
    ADMIN_STATUS_SNOOZED,
}

DEFAULT_INBOX_STATUSES = {
    ADMIN_STATUS_OPEN,
    ADMIN_STATUS_ACKNOWLEDGED,
    ADMIN_STATUS_IN_REVIEW,
}

SNOOZED_INBOX_STATUSES = {
    ADMIN_STATUS_SNOOZED,
}

TERMINAL_ADMIN_STATUSES = {
    ADMIN_STATUS_RESOLVED,
    ADMIN_STATUS_SOURCE_CLOSED,
    ADMIN_STATUS_DISMISSED,
    ADMIN_STATUS_DUPLICATE,
}


# -----------------
# Internal Helpers
# -----------------


def _alert_family(reason_code: str) -> str:
    if reason_code.startswith(("failed_", "failure_")):
        return "failed"
    if reason_code.startswith("anomaly_"):
        return "anomaly"
    if reason_code.startswith("advisory_"):
        return "advisory"
    return "other"


def _family_rank(reason_code: str) -> int:
    family = _alert_family(reason_code)
    ranks = {
        "failed": 0,
        "anomaly": 1,
        "advisory": 2,
        "other": 3,
    }
    return ranks.get(family, 3)


def _dedupe_key(
    *,
    source_slice: str,
    reason_code: str,
    request_id: str,
    target_ulid: str | None,
):
    target = target_ulid or "~"
    return f"{source_slice}:{reason_code}:{request_id}:{target}"


def _now() -> str:
    return now_iso8601_ms()


def _validate_admin_status(status: str) -> None:
    allowed = ACTIVE_ADMIN_STATUSES | TERMINAL_ADMIN_STATUSES
    if status not in allowed:
        raise ValueError(f"Unsupported admin inbox status: {status}")


def _view_statuses(view: str) -> tuple[str, set[str]]:
    normalized = (view or "active").strip().lower()
    mapping = {
        "active": DEFAULT_INBOX_STATUSES,
        "snoozed": SNOOZED_INBOX_STATUSES,
        "closed": TERMINAL_ADMIN_STATUSES,
        "all": ACTIVE_ADMIN_STATUSES | TERMINAL_ADMIN_STATUSES,
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported inbox view: {view}")
    return normalized, mapping[normalized]


def _receipt(row: AdminAlert) -> AdminAlertReceiptDTO:
    return AdminAlertReceiptDTO(
        alert_ulid=row.ulid,
        source_slice=row.source_slice,
        reason_code=row.reason_code,
        request_id=row.request_id,
        target_ulid=row.target_ulid,
        admin_status=row.admin_status,
    )


def _resolution_href(row: AdminAlert) -> str | None:
    target = dict(row.resolution_target_json or {})
    route_name = str(target.get("route_name") or "").strip()
    route_params = dict(target.get("route_params") or {})
    if not route_name:
        return None
    try:
        return url_for(route_name, **route_params)
    except Exception:
        return None


def _inbox_summary_text(view: str) -> str:
    mapping = {
        "active": "Admin triage surface for slice-owned review items and advisory notices with truthful launch paths.",
        "snoozed": "Snoozed Admin notices. Return items to the active queue when they need attention again.",
        "closed": "Closed Admin notices preserved for audit visibility. These are no longer actionable.",
        "all": "All Admin notices across active, snoozed, and closed queue posture.",
    }
    return mapping.get(view, mapping["active"])


def _set_triage_fields(
    row: AdminAlert,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> str:
    now = _now()
    row.triaged_by_actor_ulid = actor_ulid
    row.triaged_at_utc = now
    if note is not None:
        row.triage_note = note
    return now


def _require_hot_queue(row: AdminAlert) -> None:
    if row.admin_status in TERMINAL_ADMIN_STATUSES:
        raise ValueError(
            "Cannot change queue posture for a terminal admin alert"
        )


def _alert_allows_dismiss(row: AdminAlert) -> bool:
    if row.reason_code.startswith("failed_"):
        return True
    if row.reason_code == "advisory_customers_assessment_completed":
        return True
    return False


def _build_actions_summary(row: AdminAlert) -> str:
    parts = ["Open owning-slice issue"]
    if row.admin_status in {ADMIN_STATUS_OPEN, ADMIN_STATUS_SNOOZED}:
        parts.append("Acknowledge")
    if row.admin_status in {
        ADMIN_STATUS_OPEN,
        ADMIN_STATUS_ACKNOWLEDGED,
        ADMIN_STATUS_SNOOZED,
    }:
        parts.append("Start review")
    if row.admin_status in DEFAULT_INBOX_STATUSES:
        parts.append("Snooze")
    if _alert_allows_dismiss(row):
        parts.append("Dismiss info-only")
    parts.append("Mark duplicate")
    return " · ".join(parts)


def _policy_issue_from_mapping(item: dict[str, Any]) -> PolicyIssueDTO:
    return to_policy_issue(
        source=str(item.get("source") or "semantic"),
        severity=str(item.get("severity") or "error"),
        path=str(item.get("path") or ""),
        message=str(item.get("message") or ""),
    )


def _schema_state(item: dict[str, Any]) -> str:
    if not item.get("has_schema", False):
        return "missing_schema"
    if item.get("schema_ok", False):
        return "ok"
    return "error"


def _semantic_state(item: dict[str, Any]) -> str:
    if item.get("semantic_ok", False):
        return "ok"
    errors = int(item.get("semantic_error_count") or 0)
    warnings = int(item.get("semantic_warning_count") or 0)
    if errors:
        return "error"
    if warnings:
        return "warning"
    return "unknown"


def _policy_health(
    items: tuple[dict[str, Any], ...]
) -> PolicyHealthSummaryDTO:
    valid_count = 0
    warning_count = 0
    error_count = 0

    for item in items:
        schema_ok = bool(item.get("schema_ok", False))
        semantic_ok = bool(item.get("semantic_ok", False))
        semantic_warnings = int(item.get("semantic_warning_count") or 0)
        if schema_ok and semantic_ok and not semantic_warnings:
            valid_count += 1
            continue
        if (not schema_ok) or int(item.get("semantic_error_count") or 0):
            error_count += 1
            continue
        warning_count += 1

    return to_policy_health_summary(
        policy_count=len(items),
        valid_count=valid_count,
        warning_count=warning_count,
        error_count=error_count,
        last_checked_utc=_now(),
    )


def _safe_list_policies() -> tuple[dict[str, Any], ...]:
    result = governance_v2.list_policies(validate=True)
    return tuple(result.get("policies") or ())


def _safe_get_policy(key: str) -> dict[str, Any]:
    result = governance_v2.get_policy(key=key, validate=True)
    if not result.get("ok"):
        raise LookupError(f"Governance policy not found: {key}")
    return result


# -----------------
# Admin Inbox
# Services Requests
# -----------------
"""
Admin inbox rows are operational queue records only.

They do not represent the authoritative approval/authorization record.
Owning slices retain workflow truth, validation, state transitions, and
Ledger emission. Admin stores and presents triage notices for those
slice-owned workflows.

Service layer rules:
- read/compose/update Admin-local queue state only
- no commits or rollbacks here
- no Ledger emits here

Admin Inbox Cron Job Outline

archive all terminal inbox items
where admin_status in terminal_states
and still terminal at sweep time

Terminal States:
resolved
source_closed
dismissed
duplicate

Then:
copy row to AdminInboxArchive
delete from AdminInboxItem
no Ledger emit
"""


def get_alert_by_ulid(alert_ulid: str) -> AdminAlert | None:
    stmt = select(AdminAlert).where(AdminAlert.ulid == alert_ulid)
    return db.session.execute(stmt).scalar_one_or_none()


def upsert_alert(
    dto: AdminAlertUpsertDTO,
) -> AdminAlertReceiptDTO:
    """
    Create or refresh a hot-queue admin alert.

    No commit here. Caller owns transaction boundary.
    """
    dedupe_key = _dedupe_key(
        source_slice=dto.source_slice,
        reason_code=dto.reason_code,
        request_id=dto.request_id,
        target_ulid=dto.target_ulid,
    )
    now = _now()

    stmt = select(AdminAlert).where(AdminAlert.dedupe_key == dedupe_key)

    row = db.session.execute(stmt).scalar_one_or_none()

    if row is None:
        row = AdminAlert(
            ulid=new_ulid(),
            source_slice=dto.source_slice,
            reason_code=dto.reason_code,
            request_id=dto.request_id,
            target_ulid=dto.target_ulid,
            title=dto.title,
            summary=dto.summary,
            source_status=dto.source_status,
            admin_status=ADMIN_STATUS_OPEN,
            workflow_key=dto.workflow_key,
            resolution_target_json=asdict(dto.resolution_target),
            context_json=dict(dto.context or {}),
            triaged_by_actor_ulid=None,
            triaged_at_utc=None,
            snoozed_until_utc=None,
            duplicate_of_alert_ulid=None,
            triage_note=None,
            acknowledged_by_ulid=None,
            acknowledged_at_utc=None,
            closed_at_utc=None,
            close_reason=None,
            dedupe_key=dedupe_key,
        )
        db.session.add(row)
        db.session.flush()
        return _receipt(row)

    row.request_id = dto.request_id
    row.target_ulid = dto.target_ulid
    row.title = dto.title
    row.summary = dto.summary
    row.source_status = dto.source_status
    row.workflow_key = dto.workflow_key
    row.resolution_target_json = asdict(dto.resolution_target)
    row.context_json = dict(dto.context or {})
    row.updated_at_utc = now

    if row.admin_status in TERMINAL_ADMIN_STATUSES:
        raise ValueError(
            "Terminal inbox item cannot be reopened; "
            "create a new source request."
        )

    db.session.flush()
    return _receipt(row)


def close_alert(dto: AdminAlertCloseDTO) -> AdminAlertReceiptDTO | None:
    """
    Mark a hot-queue alert terminal. No reopen path is supported after
    archival; any later intervention should arrive as a new request.
    """
    _validate_admin_status(dto.admin_status)
    if dto.admin_status not in TERMINAL_ADMIN_STATUSES:
        raise ValueError("close_alert requires a terminal admin_status")

    dedupe_key = _dedupe_key(
        source_slice=dto.source_slice,
        reason_code=dto.reason_code,
        request_id=dto.request_id,
        target_ulid=dto.target_ulid,
    )

    stmt = select(AdminAlert).where(AdminAlert.dedupe_key == dedupe_key)
    row = db.session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None

    row.source_status = dto.source_status
    row.admin_status = dto.admin_status
    row.closed_at_utc = dto.closed_at_utc or _now()
    row.close_reason = dto.close_reason
    row.updated_at_utc = row.closed_at_utc

    db.session.flush()
    return _receipt(row)


def acknowledge_alert(
    alert_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> AdminAlertReceiptDTO:
    row = get_alert_by_ulid(alert_ulid)
    if row is None:
        raise LookupError(f"Admin alert not found: {alert_ulid}")
    _require_hot_queue(row)

    now = _set_triage_fields(row, actor_ulid=actor_ulid, note=note)
    row.admin_status = ADMIN_STATUS_ACKNOWLEDGED
    row.acknowledged_by_ulid = actor_ulid
    row.acknowledged_at_utc = now
    row.updated_at_utc = now

    db.session.flush()
    return _receipt(row)


def mark_alert_in_review(
    alert_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> AdminAlertReceiptDTO:
    row = get_alert_by_ulid(alert_ulid)
    if row is None:
        raise LookupError(f"Admin alert not found: {alert_ulid}")
    _require_hot_queue(row)

    now = _set_triage_fields(row, actor_ulid=actor_ulid, note=note)
    row.admin_status = ADMIN_STATUS_IN_REVIEW
    row.updated_at_utc = now

    db.session.flush()
    return _receipt(row)


def snooze_alert(
    alert_ulid: str,
    *,
    actor_ulid: str,
    snoozed_until_utc: str | None = None,
    note: str | None = None,
) -> AdminAlertReceiptDTO:
    row = get_alert_by_ulid(alert_ulid)
    if row is None:
        raise LookupError(f"Admin alert not found: {alert_ulid}")
    _require_hot_queue(row)

    now = _set_triage_fields(row, actor_ulid=actor_ulid, note=note)
    row.admin_status = ADMIN_STATUS_SNOOZED
    row.snoozed_until_utc = snoozed_until_utc
    row.updated_at_utc = now

    db.session.flush()
    return _receipt(row)


def unsnooze_alert(
    alert_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
) -> AdminAlertReceiptDTO:
    row = get_alert_by_ulid(alert_ulid)
    if row is None:
        raise LookupError(f"Admin alert not found: {alert_ulid}")
    _require_hot_queue(row)
    if row.admin_status != ADMIN_STATUS_SNOOZED:
        raise ValueError("Only snoozed alerts may be unsnoozed")

    now = _set_triage_fields(row, actor_ulid=actor_ulid, note=note)
    row.admin_status = ADMIN_STATUS_OPEN
    row.snoozed_until_utc = None
    row.updated_at_utc = now

    db.session.flush()
    return _receipt(row)


def dismiss_alert(
    alert_ulid: str,
    *,
    actor_ulid: str,
    note: str | None = None,
    close_reason: str = "admin_dismissed",
) -> AdminAlertReceiptDTO:
    row = get_alert_by_ulid(alert_ulid)
    if row is None:
        raise LookupError(f"Admin alert not found: {alert_ulid}")
    _require_hot_queue(row)
    if not _alert_allows_dismiss(row):
        raise ValueError(f"Admin alert is not dismissible: {row.reason_code}")

    now = _set_triage_fields(row, actor_ulid=actor_ulid, note=note)
    row.admin_status = ADMIN_STATUS_DISMISSED
    row.closed_at_utc = now
    row.close_reason = close_reason
    row.updated_at_utc = now

    db.session.flush()
    return _receipt(row)


def mark_alert_duplicate(
    alert_ulid: str,
    *,
    actor_ulid: str,
    duplicate_of_alert_ulid: str | None = None,
    note: str | None = None,
) -> AdminAlertReceiptDTO:
    row = get_alert_by_ulid(alert_ulid)
    if row is None:
        raise LookupError(f"Admin alert not found: {alert_ulid}")
    _require_hot_queue(row)
    if duplicate_of_alert_ulid and duplicate_of_alert_ulid == row.ulid:
        raise ValueError("Alert cannot be marked duplicate of itself")

    now = _set_triage_fields(row, actor_ulid=actor_ulid, note=note)
    row.admin_status = ADMIN_STATUS_DUPLICATE
    row.duplicate_of_alert_ulid = duplicate_of_alert_ulid
    row.closed_at_utc = now
    row.close_reason = "admin_duplicate"
    row.updated_at_utc = now

    db.session.flush()
    return _receipt(row)


def set_alert_status(
    alert_ulid: str,
    *,
    admin_status: str,
    actor_ulid: str | None = None,
    note: str | None = None,
) -> AdminAlertReceiptDTO:
    """
    Backward-compatible admin-local posture update for nonterminal states.
    Prefer explicit queue posture helpers in new code.
    """
    _validate_admin_status(admin_status)
    if admin_status in TERMINAL_ADMIN_STATUSES:
        raise ValueError("Use close_alert for slice-owned terminal states")

    row = get_alert_by_ulid(alert_ulid)
    if row is None:
        raise LookupError(f"Admin alert not found: {alert_ulid}")
    _require_hot_queue(row)

    now = _now()
    row.admin_status = admin_status

    row.updated_at_utc = now
    if actor_ulid:
        row.triaged_by_actor_ulid = actor_ulid
        row.triaged_at_utc = now
    if note is not None:
        row.triage_note = note
    if admin_status != ADMIN_STATUS_SNOOZED:
        row.snoozed_until_utc = None

    db.session.flush()
    return _receipt(row)


def archive_terminal_alerts(*, archive_reason: str = "cron_cycle") -> int:
    """
    Move terminal hot-queue items into archive and delete them from the
    active inbox table.

    No commit here. Caller owns transaction boundary.
    """
    stmt = (
        select(AdminAlert)
        .where(AdminAlert.admin_status.in_(TERMINAL_ADMIN_STATUSES))
        .order_by(
            AdminAlert.updated_at_utc.asc(),
        )
    )
    rows = list(db.session.execute(stmt).scalars().all())
    if not rows:
        return 0

    archived_at = _now()
    moved = 0

    for row in rows:
        archive_row = AdminAlertArchive(
            ulid=new_ulid(),
            original_alert_ulid=row.ulid,
            source_slice=row.source_slice,
            reason_code=row.reason_code,
            request_id=row.request_id,
            target_ulid=row.target_ulid,
            title=row.title,
            summary=row.summary,
            source_status=row.source_status,
            admin_status=row.admin_status,
            workflow_key=row.workflow_key,
            resolution_target_json=dict(row.resolution_target_json or {}),
            context_json=dict(row.context_json or {}),
            created_at_utc=row.created_at_utc,
            updated_at_utc=row.updated_at_utc,
            acknowledged_by_ulid=row.acknowledged_by_ulid,
            acknowledged_at_utc=row.acknowledged_at_utc,
            triaged_by_actor_ulid=row.triaged_by_actor_ulid,
            triaged_at_utc=row.triaged_at_utc,
            snoozed_until_utc=row.snoozed_until_utc,
            duplicate_of_alert_ulid=row.duplicate_of_alert_ulid,
            triage_note=row.triage_note,
            closed_at_utc=row.closed_at_utc,
            close_reason=row.close_reason,
            archived_at_utc=archived_at,
            archive_reason=archive_reason,
        )
        db.session.add(archive_row)
        db.session.delete(row)
        moved += 1

    db.session.flush()
    return moved


def list_inbox_alerts(*, view: str = "active") -> tuple[InboxItemDTO, ...]:
    _, statuses = _view_statuses(view)

    stmt = select(AdminAlert).where(AdminAlert.admin_status.in_(statuses))

    rows = list(db.session.execute(stmt).scalars().all())

    rows.sort(
        key=lambda row: (_family_rank(row.reason_code), row.updated_at_utc)
    )

    return tuple(
        to_inbox_item(
            alert_ulid=row.ulid,
            source_slice=row.source_slice,
            reason_code=row.reason_code,
            alert_family=_alert_family(row.reason_code),
            summary=row.summary,
            opened_at_utc=row.created_at_utc,
            status=row.admin_status,
            launch_label=str(
                (row.resolution_target_json or {}).get("launch_label")
                or "Open owning slice"
            ),
            launch_href=_resolution_href(row),
            allowed_actions_summary=_build_actions_summary(row),
            context_preview=row.title,
            can_acknowledge=row.admin_status
            in {
                ADMIN_STATUS_OPEN,
                ADMIN_STATUS_SNOOZED,
            },
            can_start_review=row.admin_status
            in {
                ADMIN_STATUS_OPEN,
                ADMIN_STATUS_ACKNOWLEDGED,
                ADMIN_STATUS_SNOOZED,
            },
            can_snooze=row.admin_status in DEFAULT_INBOX_STATUSES,
            can_dismiss=_alert_allows_dismiss(row),
            can_mark_duplicate=(
                row.admin_status not in TERMINAL_ADMIN_STATUSES
            ),
        )
        for row in rows
    )


def list_active_alerts() -> tuple[InboxItemDTO, ...]:
    return list_inbox_alerts(view="active")


def get_inbox_page(*, view: str = "active") -> InboxPageDTO:
    normalized_view, _ = _view_statuses(view)
    items = list_inbox_alerts(view=normalized_view)

    failed_count = sum(1 for item in items if item.alert_family == "failed")

    inbox_summary = to_inbox_summary(
        total_open=len(items),
        failed_count=failed_count,
        stale_count=0,
    )

    return to_inbox_page(
        title="Unified Admin Inbox",
        summary=_inbox_summary_text(normalized_view),
        inbox_summary=inbox_summary,
        current_view=normalized_view,
        items=items,
    )


# -----------------
# Cron Job Ops
# -----------------


def get_cron_page() -> CronPageDTO:
    from .services_cron import get_cron_page as build_cron_page

    return build_cron_page()


# -----------------
# Policy Maintenance
# -----------------


def get_policy_index_page() -> PolicyIndexPageDTO:
    items_raw = _safe_list_policies()
    items = tuple(
        to_policy_index_item(
            key=str(item.get("key") or ""),
            title=str(item.get("title") or item.get("key") or ""),
            status=str(item.get("status") or "unknown"),
            version=str(item.get("version") or ""),
            focus=str(item.get("focus") or ""),
            schema_state=_schema_state(item),
            semantic_state=_semantic_state(item),
            issue_count=int(item.get("issue_count") or 0),
            review_route=f"/admin/policy/{item.get('key')}/",
        )
        for item in items_raw
    )

    return to_policy_index_page(
        title="Policy Workflow Surface",
        summary=(
            "Admin frames the workflow. Governance owns policy meaning, "
            "validation, persistence, and audit semantics."
        ),
        health=_policy_health(items_raw),
        items=items,
    )


def get_policy_detail_page(policy_key: str) -> PolicyDetailPageDTO:
    item = _safe_get_policy(policy_key)

    meta = item.get("meta") or {}
    meta_items: list[PolicyMetaItemDTO] = []
    for key in (
        "title",
        "policy_key",
        "status",
        "version",
        "schema_version",
        "effective_on",
    ):
        if meta.get(key) is not None:
            meta_items.append(
                to_policy_meta_item(
                    key=key,
                    value=str(meta.get(key)),
                )
            )

    issues = tuple(
        _policy_issue_from_mapping(issue)
        for issue in item.get("issues") or ()
    )

    title = str(meta.get("title") or policy_key)
    return to_policy_detail_page(
        title=title,
        summary=(
            "Review the current policy, inspect validation state, and "
            "stage an edited document for preview."
        ),
        policy_key=policy_key,
        current_hash=str(item.get("current_hash") or ""),
        current_text=str(item.get("normalized_text") or "{}\n"),
        meta_items=tuple(meta_items),
        issues=issues,
        has_schema=bool(item.get("has_schema", False)),
        schema_ok=bool(item.get("schema_ok", False)),
        semantic_ok=bool(item.get("semantic_ok", False)),
        preview_route=f"/admin/policy/{policy_key}/preview",
    )


def build_policy_preview_page_from_parse_error(
    *,
    policy_key: str,
    policy_text: str,
    base_hash: str,
    message: str,
) -> PolicyPreviewPageDTO:
    issues = (
        to_policy_issue(
            source="parse",
            severity="error",
            path="",
            message=message,
        ),
    )
    return to_policy_preview_page(
        title=f"{policy_key} — Preview",
        summary=(
            "Preview blocked because the proposed policy text is not "
            "valid JSON."
        ),
        policy_key=policy_key,
        current_hash=base_hash,
        proposed_hash="",
        normalized_text=policy_text,
        diff_lines=(),
        issues=issues,
        change_summary=("Parse failed; no diff available.",),
        commit_allowed=False,
        commit_route=f"/admin/policy/{policy_key}/commit",
        detail_route=f"/admin/policy/{policy_key}/",
    )


def build_policy_preview_page(
    *,
    policy_key: str,
    new_policy: dict[str, Any],
    base_hash: str,
) -> PolicyPreviewPageDTO:
    result = governance_v2.preview_policy_update(
        key=policy_key,
        new_policy=new_policy,
        base_hash=base_hash,
    )

    issues = tuple(
        _policy_issue_from_mapping(issue)
        for issue in result.get("issues") or ()
    )
    summary = tuple(result.get("change_summary") or ())

    return to_policy_preview_page(
        title=f"{policy_key} — Preview",
        summary=(
            "Dry-run preview. Governance owns normalization, validation, "
            "diff generation, and commit safety checks."
        ),
        policy_key=policy_key,
        current_hash=str(result.get("current_hash") or ""),
        proposed_hash=str(result.get("proposed_hash") or ""),
        normalized_text=str(result.get("normalized_text") or "{}\n"),
        diff_lines=tuple(result.get("diff_lines") or ()),
        issues=issues,
        change_summary=summary,
        commit_allowed=bool(result.get("commit_allowed", False)),
        commit_route=f"/admin/policy/{policy_key}/commit",
        detail_route=f"/admin/policy/{policy_key}/",
    )


def commit_policy_update(
    *,
    policy_key: str,
    new_policy: dict[str, Any],
    actor_ulid: str,
    reason: str,
    base_hash: str,
    proposed_hash: str,
) -> dict[str, Any]:
    return governance_v2.commit_policy_update(
        key=policy_key,
        new_policy=new_policy,
        actor_ulid=actor_ulid,
        reason=reason,
        base_hash=base_hash,
        proposed_hash=proposed_hash,
    )


# -----------------
# RBAC Actions
# -----------------


def _role_label_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        for code, choice_label in auth_v1.list_rbac_role_choices():
            label = str(choice_label).split(" (", 1)[0].strip()
            mapping[str(code)] = label or str(code)
    except Exception:
        return {}
    return mapping


def get_auth_operators_page() -> AuthOperatorsPageDTO:
    auth_rows = auth_v1.list_user_views()
    entity_ulids = [
        str(row.get("entity_ulid"))
        for row in auth_rows
        if row.get("entity_ulid")
    ]
    label_map = (
        entity_v2.get_entity_labels(entity_ulids=entity_ulids)
        if entity_ulids
        else {}
    )
    role_labels = _role_label_map()

    active_count = 0
    disabled_count = 0
    locked_count = 0
    attention_count = 0
    items: list[dict[str, object]] = []

    for row in auth_rows:
        is_active = bool(row.get("is_active"))
        is_locked = bool(row.get("is_locked"))
        must_change = bool(row.get("must_change_password"))
        if is_active:
            active_count += 1
        else:
            disabled_count += 1
        if is_locked:
            locked_count += 1
        if (not is_active) or is_locked or must_change:
            attention_count += 1

        entity_ulid = row.get("entity_ulid")
        username = str(row.get("username") or "")
        display_name = username
        if entity_ulid:
            label = label_map.get(str(entity_ulid))
            if label is not None:
                display_name = label.display_name

        roles = tuple(row.get("roles") or ())
        role_code = str(roles[0]) if roles else None
        role_label = (
            role_labels.get(role_code, role_code) if role_code else None
        )

        items.append(
            {
                "account_ulid": str(row.get("ulid") or ""),
                "entity_ulid": (str(entity_ulid) if entity_ulid else None),
                "display_name": display_name,
                "username": username,
                "email": (
                    str(row.get("email")) if row.get("email") else None
                ),
                "role_code": role_code,
                "role_label": role_label,
                "is_active": is_active,
                "is_locked": is_locked,
                "must_change_password": must_change,
                "rbac_edit_route": f"/admin/auth/operators/{row.get('ulid')}/rbac-role",
            }
        )

    auth_summary = to_auth_operator_summary(
        active_operator_count=active_count,
        disabled_operator_count=disabled_count,
        locked_operator_count=locked_count,
        attention_count=attention_count,
    )
    return to_auth_operators_page(
        title="Auth Operator Management",
        summary=(
            "Admin surfaces operator state and launch points. Auth owns "
            "command semantics."
        ),
        auth_summary=auth_summary,
        items=tuple(items),
    )


# -----------------
# Admin Dashboard
# -----------------


def get_dashboard() -> DashboardDTO:
    inbox_items = list_active_alerts()
    failed_count = sum(
        1 for item in inbox_items if item.alert_family == "failed"
    )

    inbox_summary = to_inbox_summary(
        total_open=len(inbox_items),
        failed_count=failed_count,
        stale_count=0,
    )

    policy_summary = get_policy_index_page().health
    auth_page = get_auth_operators_page()
    auth_summary = auth_page.auth_summary
    auth_rows = auth_page.items

    slice_cards = (
        to_slice_health_card(
            slice_key="admin_inbox",
            label="Inbox",
            status="live" if inbox_items else "scaffold",
            summary="Unified Admin triage surface.",
            attention_count=len(inbox_items),
            launch_route="admin.inbox",
        ),
        to_slice_health_card(
            slice_key="admin_cron",
            label="Cron",
            status="scaffold",
            summary="Cron supervision surface scaffolded.",
            attention_count=0,
            launch_route="admin.cron",
        ),
        to_slice_health_card(
            slice_key="admin_policy",
            label="Policy",
            status=(
                "live" if policy_summary.policy_count else "not_connected"
            ),
            summary="Governance policy review and edit workflow.",
            attention_count=policy_summary.error_count,
            launch_route="admin.policy_index",
        ),
        to_slice_health_card(
            slice_key="admin_auth",
            label="Auth",
            status="live" if auth_rows else "scaffold",
            summary="Auth operator onboarding and RBAC management.",
            attention_count=auth_summary.attention_count,
            launch_route="admin.auth_operators",
        ),
    )

    recent_activity_summary = (
        "Admin control surface scaffold is live.",
        "Policy workflow now reads Governance through contracts.",
    )

    return to_dashboard(
        title="Admin Control Surface",
        summary=(
            "Observe system state, triage issues, supervise operations, "
            "and launch owning-slice workflows."
        ),
        inbox_summary=inbox_summary,
        policy_summary=policy_summary,
        auth_summary=auth_summary,
        slice_cards=slice_cards,
        recent_activity_summary=recent_activity_summary,
    )
