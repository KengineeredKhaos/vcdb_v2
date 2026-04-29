# app/slices/finance/quarantine_services.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import FinanceAdminIssue, FinanceQuarantine

STATUS_ACTIVE = "active"
STATUS_RELEASED = "released"
STATUS_SUPERSEDED = "superseded"

POSTURE_PROJECTION_BLOCKED = "projection_blocked"
POSTURE_POSTING_BLOCKED = "posting_blocked"
POSTURE_PROJECTION_AND_POSTING_BLOCKED = "projection_and_posting_blocked"

SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"
SCOPE_FUNDING_DEMAND = "funding_demand"
SCOPE_JOURNAL = "journal"
SCOPE_SEMANTIC_POSTING = "semantic_posting"
SCOPE_OPS_FLOAT = "ops_float"

VALID_SCOPES = {
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    SCOPE_FUNDING_DEMAND,
    SCOPE_JOURNAL,
    SCOPE_SEMANTIC_POSTING,
    SCOPE_OPS_FLOAT,
}

VALID_POSTURES = {
    POSTURE_PROJECTION_BLOCKED,
    POSTURE_POSTING_BLOCKED,
    POSTURE_PROJECTION_AND_POSTING_BLOCKED,
}


@dataclass(frozen=True)
class FinanceQuarantineView:
    quarantine_ulid: str
    reason_code: str
    scope_type: str
    scope_ulid: str | None
    scope_label: str | None
    source_issue_ulid: str
    request_id: str
    status: str
    posture: str
    message: str
    notes: dict[str, Any]
    opened_at_utc: str
    closed_at_utc: str | None
    closed_by_actor_ulid: str | None
    close_reason: str | None
    dedupe_key: str


def _now() -> str:
    return now_iso8601_ms()


def _to_view(row: FinanceQuarantine) -> FinanceQuarantineView:
    return FinanceQuarantineView(
        quarantine_ulid=row.ulid,
        reason_code=row.reason_code,
        scope_type=row.scope_type,
        scope_ulid=row.scope_ulid,
        scope_label=row.scope_label,
        source_issue_ulid=row.source_issue_ulid,
        request_id=row.request_id,
        status=row.status,
        posture=row.posture,
        message=row.message,
        notes=dict(row.notes_json or {}),
        opened_at_utc=row.opened_at_utc,
        closed_at_utc=row.closed_at_utc,
        closed_by_actor_ulid=row.closed_by_actor_ulid,
        close_reason=row.close_reason,
        dedupe_key=row.dedupe_key,
    )


def _get_issue(issue_ulid: str) -> FinanceAdminIssue:
    row = db.session.get(FinanceAdminIssue, issue_ulid)
    if row is None:
        raise LookupError(f"Finance admin issue not found: {issue_ulid}")
    return row


def _get_quarantine(quarantine_ulid: str) -> FinanceQuarantine:
    row = db.session.get(FinanceQuarantine, quarantine_ulid)
    if row is None:
        raise LookupError(f"Finance quarantine not found: {quarantine_ulid}")
    return row


def quarantine_dedupe_key(
    *,
    reason_code: str,
    scope_type: str,
    scope_ulid: str | None,
) -> str:
    scope_value = scope_ulid or "~"
    return f"finance:{reason_code}:{scope_type}:{scope_value}"


def _validate_scope(scope_type: str, scope_ulid: str | None) -> None:
    if scope_type not in VALID_SCOPES:
        raise ValueError(
            f"Invalid Finance quarantine scope_type: {scope_type}"
        )

    if scope_type == SCOPE_GLOBAL and scope_ulid is not None:
        raise ValueError("Global Finance quarantine must not have scope_ulid")

    if scope_type != SCOPE_GLOBAL and not scope_ulid:
        raise ValueError(
            f"Finance quarantine scope {scope_type} requires scope_ulid"
        )


def _validate_posture(posture: str) -> None:
    if posture not in VALID_POSTURES:
        raise ValueError(f"Invalid Finance quarantine posture: {posture}")


def open_or_refresh_quarantine(
    *,
    source_issue_ulid: str,
    scope_type: str,
    scope_ulid: str | None,
    posture: str,
    message: str,
    scope_label: str | None = None,
    notes: dict[str, Any] | None = None,
    actor_ulid: str | None = None,
) -> FinanceQuarantineView:
    """Open or refresh a scoped Finance safety fence.

    Canon note for Future Dev:
      A FinanceAdminIssue is the case file. FinanceQuarantine is the safety
      fence. Admin may view or launch from alerts, but Finance owns the
      question: "What scope is unsafe, and what remains safe?"
    """

    _validate_scope(scope_type, scope_ulid)
    _validate_posture(posture)

    issue = _get_issue(source_issue_ulid)
    key = quarantine_dedupe_key(
        reason_code=issue.reason_code,
        scope_type=scope_type,
        scope_ulid=scope_ulid,
    )
    now = _now()

    row = db.session.execute(
        select(FinanceQuarantine).where(FinanceQuarantine.dedupe_key == key)
    ).scalar_one_or_none()

    created = row is None
    if row is None:
        row = FinanceQuarantine(
            reason_code=issue.reason_code,
            scope_type=scope_type,
            scope_ulid=scope_ulid,
            scope_label=scope_label,
            source_issue_ulid=issue.ulid,
            request_id=issue.request_id,
            status=STATUS_ACTIVE,
            posture=posture,
            message=message,
            notes_json=dict(notes or {}),
            opened_at_utc=now,
            closed_at_utc=None,
            closed_by_actor_ulid=None,
            close_reason=None,
            dedupe_key=key,
        )
        db.session.add(row)
    else:
        row.source_issue_ulid = issue.ulid
        row.request_id = issue.request_id
        row.status = STATUS_ACTIVE
        row.posture = posture
        row.scope_label = scope_label
        row.message = message
        row.notes_json = dict(notes or {})
        row.closed_at_utc = None
        row.closed_by_actor_ulid = None
        row.close_reason = None

    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="quarantine_opened",
        request_id=issue.request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        refs={
            "quarantine_ulid": row.ulid,
            "source_issue_ulid": issue.ulid,
            "scope_type": scope_type,
            "scope_ulid": scope_ulid,
        },
        changed={
            "status": row.status,
            "posture": row.posture,
            "created": created,
        },
        meta={
            "reason_code": row.reason_code,
            "message": row.message,
        },
        chain_key="finance.quarantine",
    )

    return _to_view(row)


def release_quarantine(
    quarantine_ulid: str,
    *,
    actor_ulid: str,
    close_reason: str,
    notes: dict[str, Any] | None = None,
) -> FinanceQuarantineView:
    """Release an active Finance quarantine after proof of safety."""

    if not actor_ulid:
        raise ValueError("actor_ulid is required to release quarantine")

    close_reason = str(close_reason or "").strip()
    if not close_reason:
        raise ValueError("close_reason is required")

    row = _get_quarantine(quarantine_ulid)
    row.status = STATUS_RELEASED
    row.closed_at_utc = _now()
    row.closed_by_actor_ulid = actor_ulid
    row.close_reason = close_reason

    merged_notes = dict(row.notes_json or {})
    merged_notes.update(dict(notes or {}))
    row.notes_json = merged_notes

    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="quarantine_released",
        request_id=row.request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        refs={
            "quarantine_ulid": row.ulid,
            "source_issue_ulid": row.source_issue_ulid,
            "scope_type": row.scope_type,
            "scope_ulid": row.scope_ulid,
        },
        changed={
            "status": row.status,
            "close_reason": row.close_reason,
        },
        meta={
            "reason_code": row.reason_code,
            "message": row.message,
        },
        chain_key="finance.quarantine",
    )

    return _to_view(row)


def active_quarantines_for_scope(
    *,
    scope_type: str,
    scope_ulid: str | None,
) -> tuple[FinanceQuarantineView, ...]:
    _validate_scope(scope_type, scope_ulid)

    stmt = (
        select(FinanceQuarantine)
        .where(FinanceQuarantine.scope_type == scope_type)
        .where(FinanceQuarantine.status == STATUS_ACTIVE)
    )
    if scope_ulid is None:
        stmt = stmt.where(FinanceQuarantine.scope_ulid.is_(None))
    else:
        stmt = stmt.where(FinanceQuarantine.scope_ulid == scope_ulid)

    rows = db.session.execute(stmt).scalars().all()
    return tuple(_to_view(row) for row in rows)


def list_quarantines_for_issue(
    source_issue_ulid: str,
) -> tuple[FinanceQuarantineView, ...]:
    """List Finance quarantine fences attached to one issue.

    Used by Admin/Auditor drill-down. Quarantine visibility is part of the
    operator safety story: the issue explains what Finance found; the
    quarantine explains what Finance is blocking.
    """
    rows = (
        db.session.execute(
            select(FinanceQuarantine)
            .where(FinanceQuarantine.source_issue_ulid == source_issue_ulid)
            .order_by(
                FinanceQuarantine.status,
                FinanceQuarantine.updated_at_utc.desc(),
            )
        )
        .scalars()
        .all()
    )
    return tuple(_to_view(row) for row in rows)


__all__ = [
    "FinanceQuarantineView",
    "STATUS_ACTIVE",
    "STATUS_RELEASED",
    "STATUS_SUPERSEDED",
    "POSTURE_PROJECTION_BLOCKED",
    "POSTURE_POSTING_BLOCKED",
    "POSTURE_PROJECTION_AND_POSTING_BLOCKED",
    "SCOPE_GLOBAL",
    "SCOPE_PROJECT",
    "SCOPE_FUNDING_DEMAND",
    "SCOPE_JOURNAL",
    "SCOPE_SEMANTIC_POSTING",
    "SCOPE_OPS_FLOAT",
    "quarantine_dedupe_key",
    "open_or_refresh_quarantine",
    "release_quarantine",
    "active_quarantines_for_scope",
    "list_quarantines_for_issue",
]
