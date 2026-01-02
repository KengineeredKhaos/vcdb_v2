# app/slices/calendar/services.py
from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from app.extensions import db, event_bus
from app.extensions.policies import GOV_DATA, _load_and_cache
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

from .models import Project, ProjectFundingPlan

"""Calendar services — business logic lives here.
Projects, Tasks and Project Budgets orginate here as well.
Routes call into these functions;
services emit events via app/extensions.event_bus.
"""


class FundSummary(TypedDict, total=False):
    ulid: str
    code: str
    name: str
    restriction: str
    active: bool
    created_at_utc: str
    updated_at_utc: str


if TYPE_CHECKING:
    # type-only; won’t import at runtime
    pass

    # not actually used in code paths


def is_blackout(project_ulid: str, when_iso: str | None) -> bool:
    pol = _load_and_cache(
        GOV_DATA / "policy_calendar.json",
        "policy_calendar",
        "policy_calendar.schema.json",
    )
    # naive MVP: global blackout windows only
    windows = pol.get("global_blackouts", [])

    if not when_iso:
        when_iso = now_iso8601_ms()

    t = when_iso[:10]  # YYYY-MM-DD
    return any(w["start"] <= t <= w["end"] for w in windows)


# -----------------
# Views (PII-free projections)
# -----------------


def project_view(project_ulid: str) -> dict:
    p = db.session.get(Project, project_ulid)
    if p is None:
        raise LookupError("project not found")

    return {
        "ulid": p.ulid,
        "title": p.project_title,
        "status": p.status,
        "phase_code": p.phase_code,
        "funding_profile_key": p.funding_profile_key,
        "fund_ulid": p.fund_ulid,  # legacy
        "owner_ulid": p.owner_ulid,
        "created_at_utc": p.created_at_utc,
        "updated_at_utc": p.updated_at_utc,
    }


def task_view(task_ulid: str) -> dict:
    t = db.session.get(Task, task_ulid)
    if t is None:
        raise LookupError("task not found")

    return {
        "ulid": t.ulid,
        "project_ulid": t.project_ulid,
        "title": t.task_title,
        "detail": t.task_detail,
        "task_kind": t.task_kind,
        "estimate_cents": t.estimate_cents,
        "hours_est_minutes": t.hours_est_minutes,
        "notes_txt": t.notes_txt,
        "requirements_json": t.requirements_json,
        "assigned_to_ulid": t.assigned_to_ulid,
        "due_at_utc": t.due_at_utc,
        "done_at_utc": t.done_at_utc,
        "status": t.status,
        "created_at_utc": t.created_at_utc,
        "updated_at_utc": t.updated_at_utc,
    }


def funding_plan_view(plan_ulid: str) -> dict:
    fp = db.session.get(ProjectFundingPlan, plan_ulid)
    if fp is None:
        raise LookupError("funding plan not found")

    return {
        "ulid": fp.ulid,
        "project_ulid": fp.project_ulid,
        "label": fp.label,
        "source_kind": fp.source_kind,
        "fund_archetype_key": fp.fund_archetype_key,
        "expected_amount_cents": fp.expected_amount_cents,
        "is_in_kind": fp.is_in_kind,
        "expected_sponsor_hint": fp.expected_sponsor_hint,
        "notes": fp.notes,
        "created_at_utc": fp.created_at_utc,
        "updated_at_utc": fp.updated_at_utc,
    }


# -----------------
# Project Context
# services related
# to planning,
# budget & funding
# -----------------

# -----------------
# Create Project
# -----------------


def create_project(
    data: dict, actor_ulid: str, request_id: str | None = None
) -> dict:
    #
    # TODO:
    #
    # ADD Funding Restriction qualifier and
    # add that field to models.Project table.
    #
    """
    Create a Calendar Project and emit a domain event.

    Args:
        data:
            - project_title: str (required; falls back to "untitled")
            - fund_ulid: str | None
            - owner_ulid: str | None
            - phase_code: str | None
            - status: str | None (defaults to "planned")
        actor_ulid:
            Entity ULID of the actor creating this project.
        request_id:
            Optional correlation id (e.g. HTTP request id or ULID).
            If omitted, a new ULID will be generated for the event.

    Returns:
        dict: projection from project_view(p.ulid)
    """
    title = (data.get("project_title") or "untitled").strip()
    status = (data.get("status") or "planned").strip()

    p = Project(
        project_title=title,
        status=status,
        phase_code=data.get("phase_code"),
        owner_ulid=data.get("owner_ulid"),
        # legacy (optional; no validation here)
        fund_ulid=data.get("fund_ulid"),
        # new semantic funding key
        funding_profile_key=data.get("funding_profile_key"),
    )

    db.session.add(p)
    db.session.commit()

    rid = request_id or new_ulid()

    # PII-free event: only ULIDs + status-ish fields
    event_bus.emit(
        domain="calendar",
        operation="project_created",
        request_id=rid,
        actor_ulid=actor_ulid,
        target_ulid=p.ulid,
        changed={
            "status": p.status,
            "phase_code": p.phase_code,
        },
        refs={
            "fund_ulid": p.fund_ulid,
            "owner_ulid": p.owner_ulid,
        },
        happened_at_utc=p.created_at_utc,
    )

    return project_view(p.ulid)


# -----------------
# Create Task
# -----------------


def create_task(
    *,
    project_ulid: str,
    task_title: str,
    actor_ulid: str,
    request_id: str | None = None,
    dry_run: bool = False,
    # optional fields
    task_detail: str | None = None,
    task_kind: str | None = None,
    estimate_cents: int | None = None,
    hours_est_minutes: int | None = None,
    notes_txt: str | None = None,
    requirements_json: dict | list | None = None,
    assigned_to_ulid: str | None = None,
    due_at_utc: str | None = None,
) -> dict:
    """
    Define a project task with statement of work, staffing, logistics &
    estimated spending cost requirements to fulfill that task.

    Required fields:
    ulid (PK)
    project_ulid (FK-ish reference)
    title
    task_kind (semantic token; Governance knows what it means)
    estimate_cents (int, >= 0)

    Optional fields:
    status (optional but very useful: planned|approved|cancelled|done)
    notes (free text task description/statement of work)
    needs_json (a JSON column for manpower/equipment breakdowns)
    Do not store COA codes or expense_kind in Calendar. Keep it semantic.
    """
    if not isinstance(project_ulid, str) or len(project_ulid) != 26:
        raise ValueError("project_ulid must be a 26-char ULID")
    if (
        not task_title
        or not isinstance(task_title, str)
        or not task_title.strip()
    ):
        raise ValueError("task_title must be a non-empty string")

    p = db.session.get(Project, project_ulid)
    if p is None:
        raise LookupError("project not found")

    if estimate_cents is not None and (
        not isinstance(estimate_cents, int) or estimate_cents < 0
    ):
        raise ValueError("estimate_cents must be an int >= 0 (or None)")
    if hours_est_minutes is not None and (
        not isinstance(hours_est_minutes, int) or hours_est_minutes < 0
    ):
        raise ValueError("hours_est_minutes must be an int >= 0 (or None)")

    rid = request_id or new_ulid()

    if dry_run:
        # simulate what would be written (no DB write, no ledger emit)
        return {
            "ulid": "DRY-RUN",
            "project_ulid": project_ulid,
            "title": task_title.strip(),
            "detail": task_detail,
            "task_kind": task_kind,
            "estimate_cents": estimate_cents,
            "hours_est_minutes": hours_est_minutes,
            "notes_txt": notes_txt,
            "requirements_json": requirements_json,
            "assigned_to_ulid": assigned_to_ulid,
            "due_at_utc": due_at_utc,
            "done_at_utc": None,
            "status": "open",
            "created_at_utc": now_iso8601_ms(),
            "updated_at_utc": now_iso8601_ms(),
            "flags": ["dry_run"],
        }

    t = Task(
        project_ulid=project_ulid,
        task_title=task_title.strip(),
        task_detail=task_detail,
        task_kind=task_kind,
        estimate_cents=estimate_cents,
        hours_est_minutes=hours_est_minutes,
        notes_txt=notes_txt,
        requirements_json=requirements_json,
        assigned_to_ulid=assigned_to_ulid,
        due_at_utc=due_at_utc,
        status="open",
    )

    db.session.add(t)
    db.session.commit()

    # Emit PII-free: do NOT include notes/requirements bodies
    event_bus.emit(
        domain="calendar",
        operation="task_created",
        request_id=rid,
        actor_ulid=actor_ulid,
        target_ulid=t.ulid,
        changed={
            "status": t.status,
            "task_kind": t.task_kind,
            "estimate_cents_present": t.estimate_cents is not None,
            "requirements_present": bool(t.requirements_json),
        },
        refs={
            "project_ulid": t.project_ulid,
            "assigned_to_ulid": t.assigned_to_ulid,
        },
        happened_at_utc=t.created_at_utc,
        chain_key="calendar.task",
    )

    return task_view(t.ulid)


# -----------------
# Funding Planning
# -----------------


def create_project_funding_plan(
    data: dict,
    actor_ulid: str,
    request_id: str | None = None,
) -> dict:
    """
    Create a ProjectFundingPlan row for a Calendar Project.

    """
    project_ulid = data.get("project_ulid")
    if not isinstance(project_ulid, str) or len(project_ulid) != 26:
        raise ValueError("project_ulid must be a 26-char ULID")

    if db.session.get(Project, project_ulid) is None:
        raise LookupError("project not found")

    label = (data.get("label") or "unnamed").strip()

    expected_amount_cents = data.get("expected_amount_cents")
    if expected_amount_cents is not None:
        if (
            not isinstance(expected_amount_cents, int)
            or expected_amount_cents < 0
        ):
            raise ValueError("expected_amount_cents must be int >= 0 or None")

    fp = ProjectFundingPlan(
        project_ulid=project_ulid,
        label=label,
        source_kind=data.get("source_kind"),
        fund_archetype_key=data.get("fund_archetype_key"),
        expected_amount_cents=expected_amount_cents,
        is_in_kind=bool(data.get("is_in_kind") or False),
        expected_sponsor_hint=data.get("expected_sponsor_hint"),
        notes=data.get("notes"),
    )

    db.session.add(fp)
    db.session.commit()

    rid = request_id or new_ulid()

    event_bus.emit(
        domain="calendar",
        operation="project_funding_plan_created",
        request_id=rid,
        actor_ulid=actor_ulid,
        target_ulid=fp.ulid,
        changed={
            "source_kind": fp.source_kind,
            "fund_archetype_key": fp.fund_archetype_key,
            "expected_amount_cents": fp.expected_amount_cents,
            "is_in_kind": fp.is_in_kind,
        },
        refs={"project_ulid": fp.project_ulid},
        happened_at_utc=fp.created_at_utc,
        chain_key="calendar.project_funding_plan",
    )

    return funding_plan_view(fp.ulid)


# -----------------
# Lists
# -----------------
def list_project_funding_plans(project_ulid: str) -> list[dict]:
    rows = (
        db.session.query(ProjectFundingPlan)
        .filter(ProjectFundingPlan.project_ulid == project_ulid)
        .order_by(ProjectFundingPlan.created_at_utc.asc())
        .all()
    )
    return [funding_plan_view(r.ulid) for r in rows]


def list_tasks_for_project(project_ulid: str) -> list[dict]:
    rows = (
        db.session.query(Task)
        .filter(Task.project_ulid == project_ulid)
        .order_by(Task.created_at_utc.asc())
        .all()
    )
    return [task_view(r.ulid) for r in rows]


# -----------------
# List Project for
# a given period
# -----------------


def list_projects_for_period(period_label: str) -> list[dict]:
    """
    Return Calendar projects for a given period as plain dicts
    (ProjectDTO shape).
    """
    # If you haven't added period_label to Project yet, you can either:
    #  - add that column and filter on it, or
    #  - temporarily ignore the filter and return all projects.
    q = db.session.query(Project)

    if hasattr(Project, "period_label"):
        q = q.filter(Project.period_label == period_label)

    projects = q.order_by(Project.project_title.asc()).all()
    return [project_view(p.ulid) for p in projects]
