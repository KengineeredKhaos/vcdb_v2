# app/slices/admin/services.py
"""
VCDB v2 — Admin slice services

Read-side composition only for the Admin control surface foundation pass.
No commits, no rollbacks, no Ledger emits, no foreign write semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

from .mapper import (
    AuthOperatorsPageDTO,
    CronPageDTO,
    DashboardDTO,
    InboxItemDTO,
    InboxPageDTO,
    PolicyIndexPageDTO,
    to_auth_operator_summary,
    to_auth_operators_page,
    to_cron_job_status,
    to_cron_page,
    to_dashboard,
    to_inbox_item,
    to_inbox_page,
    to_inbox_summary,
    to_policy_health_summary,
    to_policy_index_page,
    to_slice_health_card,
)
from .models import AdminInboxArchive, AdminInboxItem

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

TERMINAL_ADMIN_STATUSES = {
    ADMIN_STATUS_RESOLVED,
    ADMIN_STATUS_SOURCE_CLOSED,
    ADMIN_STATUS_DISMISSED,
    ADMIN_STATUS_DUPLICATE,
}


# -----------------
# Internal DTO's
# -----------------


@dataclass(frozen=True)
class AdminInboxUpsertDTO:
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
    subject_ref_ulid: str | None
    severity: str
    title: str
    summary: str
    source_status: str
    workflow_key: str
    resolution_route: str
    context: dict[str, Any]
    opened_at_utc: str | None = None
    updated_at_utc: str | None = None


@dataclass(frozen=True)
class AdminInboxCloseDTO:
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
    source_status: str
    close_reason: str
    admin_status: str = ADMIN_STATUS_RESOLVED
    closed_at_utc: str | None = None


@dataclass(frozen=True)
class AdminInboxReceiptDTO:
    inbox_item_ulid: str
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
    admin_status: str


# -----------------
# Internal Helpers
# -----------------


def _dedupe_key(
    *, source_slice: str, issue_kind: str, source_ref_ulid: str
) -> str:
    return f"{source_slice}:{issue_kind}:{source_ref_ulid}"


def _now() -> str:
    return now_iso8601_ms()


def _validate_admin_status(status: str) -> None:
    allowed = ACTIVE_ADMIN_STATUSES | TERMINAL_ADMIN_STATUSES
    if status not in allowed:
        raise ValueError(f"Unsupported admin inbox status: {status}")


def _receipt(row: AdminInboxItem) -> AdminInboxReceiptDTO:
    return AdminInboxReceiptDTO(
        inbox_item_ulid=row.ulid,
        source_slice=row.source_slice,
        issue_kind=row.issue_kind,
        source_ref_ulid=row.source_ref_ulid,
        admin_status=row.admin_status,
    )


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


def get_inbox_item_by_ulid(inbox_item_ulid: str) -> AdminInboxItem | None:
    stmt = select(AdminInboxItem).where(
        AdminInboxItem.ulid == inbox_item_ulid
    )
    return db.session.execute(stmt).scalar_one_or_none()


def upsert_inbox_item(dto: AdminInboxUpsertDTO) -> AdminInboxReceiptDTO:
    """
    Create or refresh a hot-queue inbox item.

    No commit here. Caller owns transaction boundary.
    """
    dedupe_key = _dedupe_key(
        source_slice=dto.source_slice,
        issue_kind=dto.issue_kind,
        source_ref_ulid=dto.source_ref_ulid,
    )
    now = _now()

    stmt = select(AdminInboxItem).where(
        AdminInboxItem.dedupe_key == dedupe_key
    )
    row = db.session.execute(stmt).scalar_one_or_none()

    if row is None:
        row = AdminInboxItem(
            ulid=new_ulid(),
            source_slice=dto.source_slice,
            issue_kind=dto.issue_kind,
            source_ref_ulid=dto.source_ref_ulid,
            subject_ref_ulid=dto.subject_ref_ulid,
            severity=dto.severity,
            title=dto.title,
            summary=dto.summary,
            source_status=dto.source_status,
            admin_status=ADMIN_STATUS_OPEN,
            workflow_key=dto.workflow_key,
            resolution_route=dto.resolution_route,
            context_json=dict(dto.context or {}),
            opened_at_utc=dto.opened_at_utc or now,
            updated_at_utc=dto.updated_at_utc or now,
            acknowledged_by_ulid=None,
            acknowledged_at_utc=None,
            closed_at_utc=None,
            close_reason=None,
            dedupe_key=dedupe_key,
        )
        db.session.add(row)
        db.session.flush()
        return _receipt(row)

    row.subject_ref_ulid = dto.subject_ref_ulid
    row.severity = dto.severity
    row.title = dto.title
    row.summary = dto.summary
    row.source_status = dto.source_status
    row.workflow_key = dto.workflow_key
    row.resolution_route = dto.resolution_route
    row.context_json = dict(dto.context or {})
    row.updated_at_utc = dto.updated_at_utc or now

    if row.admin_status in TERMINAL_ADMIN_STATUSES:
        row.admin_status = ADMIN_STATUS_OPEN
        row.closed_at_utc = None
        row.close_reason = None
        row.acknowledged_by_ulid = None
        row.acknowledged_at_utc = None

    db.session.flush()
    return _receipt(row)


def close_inbox_item(dto: AdminInboxCloseDTO) -> AdminInboxReceiptDTO | None:
    """
    Mark a hot-queue item terminal. No reopen path is supported after
    archival; any later intervention should arrive as a new request.
    """
    _validate_admin_status(dto.admin_status)
    if dto.admin_status not in TERMINAL_ADMIN_STATUSES:
        raise ValueError("close_inbox_item requires a terminal admin_status")

    dedupe_key = _dedupe_key(
        source_slice=dto.source_slice,
        issue_kind=dto.issue_kind,
        source_ref_ulid=dto.source_ref_ulid,
    )

    stmt = select(AdminInboxItem).where(
        AdminInboxItem.dedupe_key == dedupe_key
    )
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


def acknowledge_inbox_item(
    inbox_item_ulid: str,
    *,
    actor_ulid: str,
) -> AdminInboxReceiptDTO:
    row = get_inbox_item_by_ulid(inbox_item_ulid)
    if row is None:
        raise LookupError(f"Admin inbox item not found: {inbox_item_ulid}")
    if row.admin_status in TERMINAL_ADMIN_STATUSES:
        raise ValueError("Cannot acknowledge a terminal admin inbox item")

    row.admin_status = ADMIN_STATUS_ACKNOWLEDGED
    row.acknowledged_by_ulid = actor_ulid
    row.acknowledged_at_utc = _now()
    row.updated_at_utc = row.acknowledged_at_utc

    db.session.flush()
    return _receipt(row)


def set_inbox_item_status(
    inbox_item_ulid: str,
    *,
    admin_status: str,
) -> AdminInboxReceiptDTO:
    """
    Admin-local queue posture update only.
    Intended for states like in_review or snoozed.
    """
    _validate_admin_status(admin_status)
    if admin_status in TERMINAL_ADMIN_STATUSES:
        raise ValueError("Use close_inbox_item for terminal queue states")

    row = get_inbox_item_by_ulid(inbox_item_ulid)
    if row is None:
        raise LookupError(f"Admin inbox item not found: {inbox_item_ulid}")
    if row.admin_status in TERMINAL_ADMIN_STATUSES:
        raise ValueError(
            "Cannot move a terminal item back into the hot queue"
        )

    row.admin_status = admin_status
    row.updated_at_utc = _now()

    db.session.flush()
    return _receipt(row)


def archive_terminal_items(*, archive_reason: str = "cron_cycle") -> int:
    """
    Move terminal hot-queue items into archive and delete them from the
    active inbox table.

    No commit here. Caller owns transaction boundary.
    """
    stmt = (
        select(AdminInboxItem)
        .where(AdminInboxItem.admin_status.in_(TERMINAL_ADMIN_STATUSES))
        .order_by(AdminInboxItem.updated_at_utc.asc())
    )
    rows = list(db.session.execute(stmt).scalars().all())
    if not rows:
        return 0

    archived_at = _now()
    moved = 0

    for row in rows:
        archive_row = AdminInboxArchive(
            ulid=new_ulid(),
            original_inbox_ulid=row.ulid,
            source_slice=row.source_slice,
            issue_kind=row.issue_kind,
            source_ref_ulid=row.source_ref_ulid,
            subject_ref_ulid=row.subject_ref_ulid,
            severity=row.severity,
            title=row.title,
            summary=row.summary,
            source_status=row.source_status,
            admin_status=row.admin_status,
            workflow_key=row.workflow_key,
            resolution_route=row.resolution_route,
            context_json=dict(row.context_json or {}),
            opened_at_utc=row.opened_at_utc,
            updated_at_utc=row.updated_at_utc,
            acknowledged_by_ulid=row.acknowledged_by_ulid,
            acknowledged_at_utc=row.acknowledged_at_utc,
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


def list_active_inbox_items() -> tuple[InboxItemDTO, ...]:
    stmt = (
        select(AdminInboxItem)
        .where(AdminInboxItem.admin_status.in_(ACTIVE_ADMIN_STATUSES))
        .order_by(
            AdminInboxItem.severity.desc(),
            AdminInboxItem.updated_at_utc.asc(),
        )
    )
    rows = list(db.session.execute(stmt).scalars().all())

    return tuple(
        to_inbox_item(
            source_slice=row.source_slice,
            issue_kind=row.issue_kind,
            severity=row.severity,
            summary=row.summary,
            opened_at_utc=row.opened_at_utc,
            status=row.admin_status,
            resolution_route=row.resolution_route,
            allowed_actions_summary=(
                "Launch owning-slice workflow; Admin queue actions only."
            ),
            context_preview=row.title,
        )
        for row in rows
    )


def get_inbox_page() -> InboxPageDTO:
    items = list_active_inbox_items()

    high_severity = sum(1 for item in items if item.severity == "high")

    inbox_summary = to_inbox_summary(
        total_open=len(items),
        high_severity=high_severity,
        stale_count=0,
    )

    return to_inbox_page(
        title="Unified Admin Inbox",
        summary=(
            "Admin triage surface for slice-owned review items with real "
            "resolution paths."
        ),
        inbox_summary=inbox_summary,
        items=items,
    )


# -----------------
# Cron Job Ops
# -----------------


def get_cron_page() -> CronPageDTO:
    jobs = (
        to_cron_job_status(
            job_key="admin_inbox_archive",
            label="Admin inbox archive sweep",
            status="scaffold",
            last_success_utc=None,
            last_failure_utc=None,
            stale=False,
            note="Terminal inbox items will archive on cron later.",
        ),
    )
    return to_cron_page(
        title="Cron and Maintenance Supervision",
        summary=(
            "Supervise recurring jobs, failures, stale runs, and "
            "maintenance status."
        ),
        jobs=jobs,
    )


# -----------------
# Policy Maintenance
# -----------------


def get_policy_index_page() -> PolicyIndexPageDTO:
    health = to_policy_health_summary(
        policy_count=0,
        valid_count=0,
        warning_count=0,
        error_count=0,
        last_checked_utc=None,
    )
    items = (
        {
            "key": "scaffold",
            "label": "Policy workflow scaffold",
            "status": "not_connected",
        },
    )
    return to_policy_index_page(
        title="Policy Workflow Surface",
        summary=(
            "Admin frames the workflow. Governance owns policy meaning, "
            "validation, persistence, and audit semantics."
        ),
        health=health,
        items=items,
    )


# -----------------
# RBAC Actions
# -----------------


def get_auth_operators_page() -> AuthOperatorsPageDTO:
    auth_summary = to_auth_operator_summary(
        active_operator_count=0,
        disabled_operator_count=0,
        locked_operator_count=0,
        attention_count=0,
    )
    items = (
        {
            "key": "scaffold",
            "label": "Auth operator surface scaffold",
            "status": "not_connected",
        },
    )
    return to_auth_operators_page(
        title="Auth Operator Management",
        summary=(
            "Admin surfaces operator state and launch points. Auth owns "
            "command semantics."
        ),
        auth_summary=auth_summary,
        items=items,
    )


# -----------------
# Admin Dashboard
# -----------------


def get_dashboard() -> DashboardDTO:
    inbox_items = list_active_inbox_items()
    high_severity = sum(1 for item in inbox_items if item.severity == "high")

    inbox_summary = to_inbox_summary(
        total_open=len(inbox_items),
        high_severity=high_severity,
        stale_count=0,
    )

    policy_summary = to_policy_health_summary(
        policy_count=0,
        valid_count=0,
        warning_count=0,
        error_count=0,
        last_checked_utc=None,
    )

    auth_summary = to_auth_operator_summary(
        active_operator_count=0,
        disabled_operator_count=0,
        locked_operator_count=0,
        attention_count=0,
    )

    slice_cards = (
        to_slice_health_card(
            slice_key="admin_inbox",
            label="Inbox",
            status="scaffold",
            summary="Unified Admin triage surface scaffolded.",
            attention_count=0,
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
            status="scaffold",
            summary="Policy workflow surface scaffolded.",
            attention_count=0,
            launch_route="admin.policy_index",
        ),
        to_slice_health_card(
            slice_key="admin_auth",
            label="Auth",
            status="scaffold",
            summary="Auth operator management surface scaffolded.",
            attention_count=0,
            launch_route="admin.auth_operators",
        ),
    )

    recent_activity_summary = (
        "Admin control surface scaffold is live.",
        "Routes and page shells are landing cleanly.",
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
