from __future__ import annotations

import pytest

from app.extensions import db
from app.slices.calendar.models import (
    Project,
    ProjectBudgetLine,
    ProjectBudgetSnapshot,
    Task,
)
from app.slices.calendar.services_budget import (
    add_budget_line,
    clone_snapshot,
    create_working_snapshot,
    current_budget_snapshot_view,
    delete_budget_line,
    lock_snapshot,
    update_budget_line,
)


def _make_project(*, title: str = "Budget Test Project") -> Project:
    row = Project(
        project_title=title,
        status="draft_planning",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _make_task(project_ulid: str, *, title: str = "Task A") -> Task:
    row = Task(
        project_ulid=project_ulid,
        task_title=title,
        status="open",
    )
    db.session.add(row)
    db.session.flush()
    return row


def test_create_working_snapshot_sets_current_and_project_budget_status(
    app,
    ulid,
):
    with app.app_context():
        project = _make_project()

        out = create_working_snapshot(
            project_ulid=project.ulid,
            actor_ulid=ulid(),
            snapshot_label="Initial Estimate",
            scope_summary="Whole project",
            assumptions_note="Starting point",
            request_id="req-budget-snapshot-create",
        )
        db.session.flush()

        project = db.session.get(Project, project.ulid)
        assert project is not None
        assert project.status == "budget_under_development"

        assert out["project_ulid"] == project.ulid
        assert out["snapshot_label"] == "Initial Estimate"
        assert out["is_current"] is True
        assert out["is_locked"] is False
        assert out["gross_cost_cents"] == 0
        assert out["expected_offset_cents"] == 0
        assert out["net_need_cents"] == 0

        current = current_budget_snapshot_view(project.ulid)
        assert current is not None
        assert current["ulid"] == out["ulid"]


def test_add_update_delete_budget_lines_recalculate_snapshot_totals(
    app,
    ulid,
):
    with app.app_context():
        project = _make_project()
        task = _make_task(project.ulid, title="Assemble kits")
        snapshot = create_working_snapshot(
            project_ulid=project.ulid,
            actor_ulid=ulid(),
            snapshot_label="Working",
        )

        cost_line = add_budget_line(
            snapshot_ulid=snapshot["ulid"],
            actor_ulid=ulid(),
            task_ulid=task.ulid,
            label="Bedding pack",
            line_kind="materials",
            estimated_total_cents=12500,
            basis_qty=5,
            basis_unit="kits",
            unit_cost_cents=2500,
        )
        offset_line = add_budget_line(
            snapshot_ulid=snapshot["ulid"],
            actor_ulid=ulid(),
            label="Expected in-kind donation",
            line_kind="goods",
            estimated_total_cents=3000,
            is_offset=True,
            offset_kind="in_kind",
        )
        db.session.flush()

        rolled = db.session.get(ProjectBudgetSnapshot, snapshot["ulid"])
        assert rolled is not None
        assert rolled.gross_cost_cents == 12500
        assert rolled.expected_offset_cents == 3000
        assert rolled.net_need_cents == 9500

        updated = update_budget_line(
            line_ulid=cost_line["ulid"],
            actor_ulid=ulid(),
            estimated_total_cents=15000,
        )
        db.session.flush()
        assert updated["estimated_total_cents"] == 15000

        rolled = db.session.get(ProjectBudgetSnapshot, snapshot["ulid"])
        assert rolled is not None
        assert rolled.gross_cost_cents == 15000
        assert rolled.expected_offset_cents == 3000
        assert rolled.net_need_cents == 12000

        deleted = delete_budget_line(
            line_ulid=offset_line["ulid"],
            actor_ulid=ulid(),
        )
        db.session.flush()
        assert deleted["deleted"] is True

        rolled = db.session.get(ProjectBudgetSnapshot, snapshot["ulid"])
        assert rolled is not None
        assert rolled.gross_cost_cents == 15000
        assert rolled.expected_offset_cents == 0
        assert rolled.net_need_cents == 15000


def test_clone_snapshot_copies_lines_and_sets_new_snapshot_current(app, ulid):
    with app.app_context():
        project = _make_project(title="Clone Test Project")
        task = _make_task(project.ulid, title="Task for clone")
        original = create_working_snapshot(
            project_ulid=project.ulid,
            actor_ulid=ulid(),
            snapshot_label="Original",
        )
        add_budget_line(
            snapshot_ulid=original["ulid"],
            actor_ulid=ulid(),
            task_ulid=task.ulid,
            label="Original line",
            line_kind="materials",
            estimated_total_cents=4200,
        )
        db.session.flush()

        cloned = clone_snapshot(
            snapshot_ulid=original["ulid"],
            actor_ulid=ulid(),
            snapshot_label="Revision A",
        )
        db.session.flush()

        original_row = db.session.get(ProjectBudgetSnapshot, original["ulid"])
        cloned_row = db.session.get(ProjectBudgetSnapshot, cloned["ulid"])
        assert original_row is not None
        assert cloned_row is not None
        assert original_row.is_current is False
        assert cloned_row.is_current is True
        assert cloned_row.based_on_snapshot_ulid == original_row.ulid

        original_lines = db.session.query(ProjectBudgetLine).filter_by(
            budget_snapshot_ulid=original_row.ulid
        ).all()
        cloned_lines = db.session.query(ProjectBudgetLine).filter_by(
            budget_snapshot_ulid=cloned_row.ulid
        ).all()

        assert len(original_lines) == 1
        assert len(cloned_lines) == 1
        assert cloned_lines[0].ulid != original_lines[0].ulid
        assert cloned_lines[0].copied_from_line_ulid == original_lines[0].ulid
        assert cloned_row.gross_cost_cents == 4200
        assert cloned_row.net_need_cents == 4200


def test_lock_snapshot_freezes_mutations_and_marks_project_budget_ready(app, ulid):
    with app.app_context():
        project = _make_project(title="Lock Test Project")
        snapshot = create_working_snapshot(
            project_ulid=project.ulid,
            actor_ulid=ulid(),
            snapshot_label="Ready to Lock",
        )
        line = add_budget_line(
            snapshot_ulid=snapshot["ulid"],
            actor_ulid=ulid(),
            label="Cash cost",
            line_kind="services",
            estimated_total_cents=8000,
        )
        db.session.flush()

        locked = lock_snapshot(
            snapshot_ulid=snapshot["ulid"],
            actor_ulid=ulid(),
        )
        db.session.flush()

        project = db.session.get(Project, project.ulid)
        assert project is not None
        assert project.status == "budget_ready"
        assert locked["is_locked"] is True
        assert locked["locked_at_utc"] is not None

        with pytest.raises(RuntimeError):
            add_budget_line(
                snapshot_ulid=snapshot["ulid"],
                actor_ulid=ulid(),
                label="Late add",
                line_kind="materials",
                estimated_total_cents=100,
            )

        with pytest.raises(RuntimeError):
            update_budget_line(
                line_ulid=line["ulid"],
                actor_ulid=ulid(),
                estimated_total_cents=9000,
            )

        with pytest.raises(RuntimeError):
            delete_budget_line(
                line_ulid=line["ulid"],
                actor_ulid=ulid(),
            )


def test_add_budget_line_rejects_task_from_another_project(app, ulid):
    with app.app_context():
        project_a = _make_project(title="Project A")
        project_b = _make_project(title="Project B")
        foreign_task = _make_task(project_b.ulid, title="Foreign task")
        snapshot = create_working_snapshot(
            project_ulid=project_a.ulid,
            actor_ulid=ulid(),
            snapshot_label="Snapshot A",
        )

        with pytest.raises(RuntimeError):
            add_budget_line(
                snapshot_ulid=snapshot["ulid"],
                actor_ulid=ulid(),
                task_ulid=foreign_task.ulid,
                label="Should fail",
                line_kind="materials",
                estimated_total_cents=500,
            )
