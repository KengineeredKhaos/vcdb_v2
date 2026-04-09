# app/slices/calendar/services_budget.py

"""Calendar budget services.

This module is intentionally boring and explicit.

Rules:
- Project is the aggregate root.
- Budget snapshots are the canonical budget basis.
- Budget lines are the canonical money-planning records.
- Locked snapshots are immutable.
- Snapshot totals are always derived from lines.
- No commit/rollback here; routes own the transaction boundary.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

from .models import Project, ProjectBudgetLine, ProjectBudgetSnapshot, Task
from .taxonomy import PROJECT_STATUSES

_ALLOWED_PROJECT_STATUSES = set(PROJECT_STATUSES)
_EDITABLE_PROJECT_STATUSES = {
    "draft_planning",
    "tasking_in_progress",
    "budget_under_development",
    "budget_ready",
}


def _require_ulid(name: str, value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) != 26:
        raise ValueError(f"{name} must be a 26-char ULID")
    return text


def _clean_text(
    value: str | None, *, default: str | None = None
) -> str | None:
    text = str(value or "").strip()
    if text:
        return text
    return default


def _get_project_or_raise(project_ulid: str) -> Project:
    _require_ulid("project_ulid", project_ulid)
    row = db.session.execute(
        select(Project).where(Project.ulid == project_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"project not found: {project_ulid}")
    return row


def _get_snapshot_or_raise(snapshot_ulid: str) -> ProjectBudgetSnapshot:
    _require_ulid("snapshot_ulid", snapshot_ulid)
    row = db.session.execute(
        select(ProjectBudgetSnapshot).where(
            ProjectBudgetSnapshot.ulid == snapshot_ulid
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"budget snapshot not found: {snapshot_ulid}")
    return row


def _get_line_or_raise(line_ulid: str) -> ProjectBudgetLine:
    _require_ulid("line_ulid", line_ulid)
    row = db.session.execute(
        select(ProjectBudgetLine).where(ProjectBudgetLine.ulid == line_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"budget line not found: {line_ulid}")
    return row


def _get_task_or_raise(task_ulid: str) -> Task:
    _require_ulid("task_ulid", task_ulid)
    row = db.session.execute(
        select(Task).where(Task.ulid == task_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"task not found: {task_ulid}")
    return row


def _require_unlocked(snapshot: ProjectBudgetSnapshot) -> None:
    if bool(snapshot.is_locked):
        raise RuntimeError("budget snapshot is locked")


def _assert_task_matches_project(*, task: Task, project_ulid: str) -> None:
    if str(task.project_ulid or "") != str(project_ulid or ""):
        raise RuntimeError("task does not belong to snapshot project")


def _set_only_current_snapshot(
    *,
    project_ulid: str,
    snapshot_ulid: str,
) -> None:
    rows = db.session.execute(
        select(ProjectBudgetSnapshot).where(
            ProjectBudgetSnapshot.project_ulid == project_ulid
        )
    ).scalars()
    for row in rows:
        row.is_current = row.ulid == snapshot_ulid


def _next_sort_order(snapshot_ulid: str) -> int:
    rows = db.session.execute(
        select(ProjectBudgetLine).where(
            ProjectBudgetLine.budget_snapshot_ulid == snapshot_ulid
        )
    ).scalars()
    max_sort = -10
    for row in rows:
        max_sort = max(max_sort, int(row.sort_order or 0))
    return max_sort + 10


def _normalize_money(value: int | None, *, field: str) -> int:
    cents = int(value or 0)
    if cents < 0:
        raise ValueError(f"{field} must be >= 0")
    return cents


def _normalize_optional_nonneg(
    value: int | None, *, field: str
) -> int | None:
    if value is None:
        return None
    number = int(value)
    if number < 0:
        raise ValueError(f"{field} must be >= 0")
    return number


def _sync_project_budget_status(project: Project) -> None:
    current = str(project.status or "").strip()
    if current not in _ALLOWED_PROJECT_STATUSES:
        current = "draft_planning"

    if current in {"execution_underway", "closeout_pending", "closed"}:
        return

    has_locked_snapshot = (
        db.session.execute(
            select(ProjectBudgetSnapshot).where(
                ProjectBudgetSnapshot.project_ulid == project.ulid,
                ProjectBudgetSnapshot.is_locked.is_(True),
            )
        ).first()
        is not None
    )

    has_any_snapshot = (
        db.session.execute(
            select(ProjectBudgetSnapshot).where(
                ProjectBudgetSnapshot.project_ulid == project.ulid,
            )
        ).first()
        is not None
    )

    if has_locked_snapshot:
        project.status = "budget_ready"
        return

    if has_any_snapshot and current in _EDITABLE_PROJECT_STATUSES:
        project.status = "budget_under_development"


def _emit(
    *,
    operation: str,
    actor_ulid: str,
    target_ulid: str,
    happened_at_utc: str | None = None,
    request_id: str | None = None,
    refs: dict[str, Any] | None = None,
    changed: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    event_bus.emit(
        domain="calendar",
        operation=operation,
        request_id=request_id or new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=target_ulid,
        happened_at_utc=happened_at_utc or now_iso8601_ms(),
        refs=refs or {},
        changed=changed or {},
        meta=meta or {},
    )


def budget_snapshot_view(snapshot_ulid: str) -> dict[str, Any]:
    row = _get_snapshot_or_raise(snapshot_ulid)
    return {
        "ulid": row.ulid,
        "project_ulid": row.project_ulid,
        "snapshot_label": row.snapshot_label,
        "scope_summary": row.scope_summary,
        "gross_cost_cents": int(row.gross_cost_cents or 0),
        "expected_offset_cents": int(row.expected_offset_cents or 0),
        "net_need_cents": int(row.net_need_cents or 0),
        "assumptions_note": row.assumptions_note,
        "based_on_snapshot_ulid": row.based_on_snapshot_ulid,
        "is_current": bool(row.is_current),
        "is_locked": bool(row.is_locked),
        "locked_at_utc": row.locked_at_utc,
        "created_at_utc": row.created_at_utc,
        "updated_at_utc": row.updated_at_utc,
    }


def budget_line_view(line_ulid: str) -> dict[str, Any]:
    row = _get_line_or_raise(line_ulid)
    return {
        "ulid": row.ulid,
        "budget_snapshot_ulid": row.budget_snapshot_ulid,
        "task_ulid": row.task_ulid,
        "line_kind": row.line_kind,
        "label": row.label,
        "detail": row.detail,
        "basis_qty": row.basis_qty,
        "basis_unit": row.basis_unit,
        "unit_cost_cents": row.unit_cost_cents,
        "estimated_total_cents": int(row.estimated_total_cents or 0),
        "is_offset": bool(row.is_offset),
        "offset_kind": row.offset_kind,
        "sort_order": int(row.sort_order or 0),
        "copied_from_line_ulid": row.copied_from_line_ulid,
        "created_at_utc": row.created_at_utc,
        "updated_at_utc": row.updated_at_utc,
    }


def list_budget_snapshots(project_ulid: str) -> list[dict[str, Any]]:
    _get_project_or_raise(project_ulid)
    rows = db.session.execute(
        select(ProjectBudgetSnapshot)
        .where(ProjectBudgetSnapshot.project_ulid == project_ulid)
        .order_by(
            ProjectBudgetSnapshot.is_current.desc(),
            ProjectBudgetSnapshot.created_at_utc.desc(),
        )
    ).scalars()
    return [budget_snapshot_view(row.ulid) for row in rows]


def list_budget_lines(snapshot_ulid: str) -> list[dict[str, Any]]:
    _get_snapshot_or_raise(snapshot_ulid)
    rows = db.session.execute(
        select(ProjectBudgetLine)
        .where(ProjectBudgetLine.budget_snapshot_ulid == snapshot_ulid)
        .order_by(
            ProjectBudgetLine.sort_order.asc(), ProjectBudgetLine.label.asc()
        )
    ).scalars()
    return [budget_line_view(row.ulid) for row in rows]


def current_budget_snapshot_view(project_ulid: str) -> dict[str, Any] | None:
    _get_project_or_raise(project_ulid)
    row = db.session.execute(
        select(ProjectBudgetSnapshot)
        .where(
            ProjectBudgetSnapshot.project_ulid == project_ulid,
            ProjectBudgetSnapshot.is_current.is_(True),
        )
        .order_by(ProjectBudgetSnapshot.created_at_utc.desc())
    ).scalar_one_or_none()
    if row is None:
        return None
    return budget_snapshot_view(row.ulid)


def create_working_snapshot(
    *,
    project_ulid: str,
    actor_ulid: str,
    snapshot_label: str | None = None,
    scope_summary: str | None = None,
    assumptions_note: str | None = None,
    based_on_snapshot_ulid: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    project = _get_project_or_raise(project_ulid)
    _require_ulid("actor_ulid", actor_ulid)

    based_on: ProjectBudgetSnapshot | None = None
    if based_on_snapshot_ulid:
        based_on = _get_snapshot_or_raise(based_on_snapshot_ulid)
        if based_on.project_ulid != project.ulid:
            raise RuntimeError(
                "based_on_snapshot_ulid belongs to another project"
            )

    row = ProjectBudgetSnapshot(
        project_ulid=project.ulid,
        snapshot_label=(
            _clean_text(snapshot_label, default="working budget")
            or "working budget"
        ),
        scope_summary=_clean_text(scope_summary),
        gross_cost_cents=0,
        expected_offset_cents=0,
        net_need_cents=0,
        assumptions_note=_clean_text(assumptions_note),
        based_on_snapshot_ulid=(
            based_on.ulid if based_on is not None else None
        ),
        is_current=True,
        is_locked=False,
        locked_at_utc=None,
    )
    db.session.add(row)
    db.session.flush()

    _set_only_current_snapshot(
        project_ulid=project.ulid, snapshot_ulid=row.ulid
    )
    _sync_project_budget_status(project)
    db.session.flush()

    _emit(
        operation="budget_snapshot_created",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=row.created_at_utc,
        refs={
            "project_ulid": project.ulid,
            "based_on_snapshot_ulid": row.based_on_snapshot_ulid,
        },
        changed={
            "fields": [
                "snapshot_label",
                "scope_summary",
                "assumptions_note",
                "is_current",
                "is_locked",
            ]
        },
    )
    return budget_snapshot_view(row.ulid)


def clone_snapshot(
    *,
    snapshot_ulid: str,
    actor_ulid: str,
    snapshot_label: str | None = None,
    scope_summary: str | None = None,
    assumptions_note: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    source = _get_snapshot_or_raise(snapshot_ulid)
    project = _get_project_or_raise(source.project_ulid)
    _require_ulid("actor_ulid", actor_ulid)

    clone = ProjectBudgetSnapshot(
        project_ulid=project.ulid,
        snapshot_label=(
            _clean_text(
                snapshot_label, default=f"{source.snapshot_label} copy"
            )
            or f"{source.snapshot_label} copy"
        ),
        scope_summary=(
            _clean_text(scope_summary)
            if scope_summary is not None
            else source.scope_summary
        ),
        gross_cost_cents=0,
        expected_offset_cents=0,
        net_need_cents=0,
        assumptions_note=(
            _clean_text(assumptions_note)
            if assumptions_note is not None
            else source.assumptions_note
        ),
        based_on_snapshot_ulid=source.ulid,
        is_current=True,
        is_locked=False,
        locked_at_utc=None,
    )
    db.session.add(clone)
    db.session.flush()

    source_lines = db.session.execute(
        select(ProjectBudgetLine)
        .where(ProjectBudgetLine.budget_snapshot_ulid == source.ulid)
        .order_by(
            ProjectBudgetLine.sort_order.asc(),
            ProjectBudgetLine.created_at_utc.asc(),
        )
    ).scalars()

    count = 0
    for src in source_lines:
        db.session.add(
            ProjectBudgetLine(
                budget_snapshot_ulid=clone.ulid,
                task_ulid=src.task_ulid,
                line_kind=src.line_kind,
                label=src.label,
                detail=src.detail,
                basis_qty=src.basis_qty,
                basis_unit=src.basis_unit,
                unit_cost_cents=src.unit_cost_cents,
                estimated_total_cents=int(src.estimated_total_cents or 0),
                is_offset=bool(src.is_offset),
                offset_kind=src.offset_kind,
                sort_order=int(src.sort_order or 0),
                copied_from_line_ulid=src.ulid,
            )
        )
        count += 1

    db.session.flush()
    recalculate_snapshot(snapshot_ulid=clone.ulid)
    _set_only_current_snapshot(
        project_ulid=project.ulid, snapshot_ulid=clone.ulid
    )
    _sync_project_budget_status(project)
    db.session.flush()

    _emit(
        operation="budget_snapshot_cloned",
        actor_ulid=actor_ulid,
        target_ulid=clone.ulid,
        request_id=request_id,
        happened_at_utc=clone.created_at_utc,
        refs={
            "project_ulid": project.ulid,
            "source_snapshot_ulid": source.ulid,
        },
        changed={"copied_line_count": count},
    )
    return budget_snapshot_view(clone.ulid)


def set_current_snapshot(
    *,
    project_ulid: str,
    snapshot_ulid: str,
    actor_ulid: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    project = _get_project_or_raise(project_ulid)
    snapshot = _get_snapshot_or_raise(snapshot_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    if snapshot.project_ulid != project.ulid:
        raise RuntimeError("snapshot belongs to another project")

    _set_only_current_snapshot(
        project_ulid=project.ulid, snapshot_ulid=snapshot.ulid
    )
    db.session.flush()

    _emit(
        operation="budget_snapshot_set_current",
        actor_ulid=actor_ulid,
        target_ulid=snapshot.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"project_ulid": project.ulid},
        changed={"fields": ["is_current"]},
    )
    return budget_snapshot_view(snapshot.ulid)


def add_budget_line(
    *,
    snapshot_ulid: str,
    actor_ulid: str,
    label: str,
    line_kind: str,
    estimated_total_cents: int,
    task_ulid: str | None = None,
    detail: str | None = None,
    basis_qty: int | None = None,
    basis_unit: str | None = None,
    unit_cost_cents: int | None = None,
    is_offset: bool = False,
    offset_kind: str | None = None,
    sort_order: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_raise(snapshot_ulid)
    project = _get_project_or_raise(snapshot.project_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_unlocked(snapshot)

    clean_label = _clean_text(label)
    clean_kind = _clean_text(line_kind)
    if not clean_label:
        raise ValueError("label is required")
    if not clean_kind:
        raise ValueError("line_kind is required")

    cents = _normalize_money(
        estimated_total_cents, field="estimated_total_cents"
    )
    qty = _normalize_optional_nonneg(basis_qty, field="basis_qty")
    unit_cost = _normalize_optional_nonneg(
        unit_cost_cents, field="unit_cost_cents"
    )

    clean_offset_kind = _clean_text(offset_kind)
    if is_offset and not clean_offset_kind:
        raise ValueError("offset_kind is required when is_offset is true")
    if (not is_offset) and clean_offset_kind:
        raise ValueError("offset_kind must be empty when is_offset is false")

    task: Task | None = None
    if task_ulid:
        task = _get_task_or_raise(task_ulid)
        _assert_task_matches_project(task=task, project_ulid=project.ulid)

    row = ProjectBudgetLine(
        budget_snapshot_ulid=snapshot.ulid,
        task_ulid=(task.ulid if task is not None else None),
        line_kind=clean_kind,
        label=clean_label,
        detail=_clean_text(detail),
        basis_qty=qty,
        basis_unit=_clean_text(basis_unit),
        unit_cost_cents=unit_cost,
        estimated_total_cents=cents,
        is_offset=bool(is_offset),
        offset_kind=clean_offset_kind,
        sort_order=(
            _normalize_optional_nonneg(sort_order, field="sort_order")
            if sort_order is not None
            else _next_sort_order(snapshot.ulid)
        )
        or 0,
        copied_from_line_ulid=None,
    )
    db.session.add(row)
    db.session.flush()
    recalculate_snapshot(snapshot_ulid=snapshot.ulid)
    _sync_project_budget_status(project)
    db.session.flush()

    _emit(
        operation="budget_line_added",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=row.created_at_utc,
        refs={
            "project_ulid": project.ulid,
            "snapshot_ulid": snapshot.ulid,
            "task_ulid": row.task_ulid,
        },
        changed={
            "fields": [
                "line_kind",
                "label",
                "estimated_total_cents",
                "is_offset",
                "offset_kind",
                "sort_order",
            ]
        },
    )
    return budget_line_view(row.ulid)


def update_budget_line(
    *,
    line_ulid: str,
    actor_ulid: str,
    label: str | None = None,
    line_kind: str | None = None,
    estimated_total_cents: int | None = None,
    task_ulid: str | None = None,
    detail: str | None = None,
    basis_qty: int | None = None,
    basis_unit: str | None = None,
    unit_cost_cents: int | None = None,
    is_offset: bool | None = None,
    offset_kind: str | None = None,
    sort_order: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_line_or_raise(line_ulid)
    snapshot = _get_snapshot_or_raise(row.budget_snapshot_ulid)
    project = _get_project_or_raise(snapshot.project_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_unlocked(snapshot)

    changed_fields: list[str] = []

    if label is not None:
        clean_label = _clean_text(label)
        if not clean_label:
            raise ValueError("label cannot be blank")
        row.label = clean_label
        changed_fields.append("label")

    if line_kind is not None:
        clean_kind = _clean_text(line_kind)
        if not clean_kind:
            raise ValueError("line_kind cannot be blank")
        row.line_kind = clean_kind
        changed_fields.append("line_kind")

    if estimated_total_cents is not None:
        row.estimated_total_cents = _normalize_money(
            estimated_total_cents,
            field="estimated_total_cents",
        )
        changed_fields.append("estimated_total_cents")

    if detail is not None:
        row.detail = _clean_text(detail)
        changed_fields.append("detail")

    if basis_qty is not None:
        row.basis_qty = _normalize_optional_nonneg(
            basis_qty, field="basis_qty"
        )
        changed_fields.append("basis_qty")

    if basis_unit is not None:
        row.basis_unit = _clean_text(basis_unit)
        changed_fields.append("basis_unit")

    if unit_cost_cents is not None:
        row.unit_cost_cents = _normalize_optional_nonneg(
            unit_cost_cents,
            field="unit_cost_cents",
        )
        changed_fields.append("unit_cost_cents")

    if sort_order is not None:
        row.sort_order = (
            _normalize_optional_nonneg(sort_order, field="sort_order") or 0
        )
        changed_fields.append("sort_order")

    if task_ulid is not None:
        clean_task_ulid = str(task_ulid).strip()
        if not clean_task_ulid:
            row.task_ulid = None
        else:
            task = _get_task_or_raise(clean_task_ulid)
            _assert_task_matches_project(task=task, project_ulid=project.ulid)
            row.task_ulid = task.ulid
        changed_fields.append("task_ulid")

    new_is_offset = row.is_offset if is_offset is None else bool(is_offset)
    new_offset_kind = (
        row.offset_kind if offset_kind is None else _clean_text(offset_kind)
    )
    if new_is_offset and not new_offset_kind:
        raise ValueError("offset_kind is required when is_offset is true")
    if (not new_is_offset) and new_offset_kind:
        raise ValueError("offset_kind must be empty when is_offset is false")
    if is_offset is not None:
        row.is_offset = bool(is_offset)
        changed_fields.append("is_offset")
    if offset_kind is not None:
        row.offset_kind = _clean_text(offset_kind)
        changed_fields.append("offset_kind")

    db.session.flush()
    recalculate_snapshot(snapshot_ulid=snapshot.ulid)
    _sync_project_budget_status(project)
    db.session.flush()

    _emit(
        operation="budget_line_updated",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": project.ulid,
            "snapshot_ulid": snapshot.ulid,
            "task_ulid": row.task_ulid,
        },
        changed={"fields": changed_fields},
    )
    return budget_line_view(row.ulid)


def delete_budget_line(
    *,
    line_ulid: str,
    actor_ulid: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_line_or_raise(line_ulid)
    snapshot = _get_snapshot_or_raise(row.budget_snapshot_ulid)
    project = _get_project_or_raise(snapshot.project_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_unlocked(snapshot)

    deleted_ulid = row.ulid
    db.session.delete(row)
    db.session.flush()
    recalculate_snapshot(snapshot_ulid=snapshot.ulid)
    _sync_project_budget_status(project)
    db.session.flush()

    _emit(
        operation="budget_line_deleted",
        actor_ulid=actor_ulid,
        target_ulid=deleted_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": project.ulid,
            "snapshot_ulid": snapshot.ulid,
        },
    )
    return {
        "deleted": True,
        "line_ulid": deleted_ulid,
        "snapshot_ulid": snapshot.ulid,
    }


def recalculate_snapshot(
    *,
    snapshot_ulid: str,
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_raise(snapshot_ulid)
    rows = db.session.execute(
        select(ProjectBudgetLine).where(
            ProjectBudgetLine.budget_snapshot_ulid == snapshot.ulid
        )
    ).scalars()

    gross = 0
    offset = 0
    for row in rows:
        cents = int(row.estimated_total_cents or 0)
        if bool(row.is_offset):
            offset += cents
        else:
            gross += cents

    net = gross - offset
    if net < 0:
        net = 0

    snapshot.gross_cost_cents = gross
    snapshot.expected_offset_cents = offset
    snapshot.net_need_cents = net
    db.session.flush()
    return budget_snapshot_view(snapshot.ulid)


def lock_snapshot(
    *,
    snapshot_ulid: str,
    actor_ulid: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_raise(snapshot_ulid)
    project = _get_project_or_raise(snapshot.project_ulid)
    _require_ulid("actor_ulid", actor_ulid)

    if bool(snapshot.is_locked):
        raise RuntimeError("budget snapshot already locked")

    line_count = db.session.execute(
        select(ProjectBudgetLine).where(
            ProjectBudgetLine.budget_snapshot_ulid == snapshot.ulid
        )
    ).first()
    if line_count is None:
        raise RuntimeError("cannot lock a budget snapshot with no lines")

    recalculate_snapshot(snapshot_ulid=snapshot.ulid)
    snapshot.is_locked = True
    snapshot.locked_at_utc = now_iso8601_ms()
    _sync_project_budget_status(project)
    db.session.flush()
    _sync_project_budget_status(project)
    db.session.flush()

    _emit(
        operation="budget_snapshot_locked",
        actor_ulid=actor_ulid,
        target_ulid=snapshot.ulid,
        request_id=request_id,
        happened_at_utc=snapshot.locked_at_utc,
        refs={"project_ulid": project.ulid},
        changed={"fields": ["is_locked", "locked_at_utc"]},
    )
    return budget_snapshot_view(snapshot.ulid)


__all__ = [
    "add_budget_line",
    "budget_line_view",
    "budget_snapshot_view",
    "clone_snapshot",
    "create_working_snapshot",
    "current_budget_snapshot_view",
    "delete_budget_line",
    "list_budget_lines",
    "list_budget_snapshots",
    "lock_snapshot",
    "recalculate_snapshot",
    "set_current_snapshot",
    "update_budget_line",
]
