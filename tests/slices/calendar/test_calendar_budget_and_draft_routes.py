# tests/slices/calendar/test_calendar_budget_and_draft_routes.py

from __future__ import annotations

import re
from types import SimpleNamespace

from app.extensions import db
from app.slices.calendar.models import (
    DemandDraft,
    FundingDemand,
    Project,
    ProjectBudgetLine,
    ProjectBudgetSnapshot,
    Task,
)
from app.slices.calendar.services_budget import (
    add_budget_line,
    create_working_snapshot,
    lock_snapshot,
)


def _extract_csrf_token(html: str) -> str:
    match = re.search(
        r'name="csrf_token".*?value="([^"]+)"',
        html,
        re.DOTALL,
    )
    assert match, "csrf_token not found in form HTML"
    return match.group(1)


def _get_csrf_token(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    return _extract_csrf_token(resp.get_data(as_text=True))


def _patch_governance_ok(monkeypatch) -> None:
    from app.extensions.contracts import governance_v2
    from app.slices.calendar import services_drafts as drafts_svc

    monkeypatch.setattr(
        drafts_svc.gov,
        "validate_semantic_keys",
        lambda **kwargs: SimpleNamespace(ok=True, errors=[]),
    )
    monkeypatch.setattr(
        drafts_svc.gov,
        "get_funding_source_profile_summary",
        lambda key: governance_v2.FundingSourceProfileSummaryDTO(
            key=key,
            source_kind="grant",
            support_mode="reimbursement",
            approval_posture="standard",
            default_restriction_keys=("local_only",),
            bridge_allowed=False,
            repayment_expectation="none",
            forgiveness_rule="not_applicable",
            auto_ops_bridge_on_publish=False,
        ),
    )
    monkeypatch.setattr(
        drafts_svc.gov,
        "review_calendar_demand",
        lambda req: governance_v2.GovernanceReviewDecisionDTO(
            decision="approved",
            governance_note="Governance semantics approved for publish.",
            approved_spending_class=req.spending_class_candidate,
            approved_source_profile_key=req.source_profile_key_candidate,
            eligible_fund_codes=("general_unrestricted",),
            default_restriction_keys=("local_only",),
            approved_tag_any=tuple(req.tag_any or ()),
            decision_fingerprint="fp-draft-review",
            validation_errors=(),
            reason_codes=("source_profile:test",),
            matched_rule_ids=("selector:test",),
        ),
    )


def _patch_route_choices(monkeypatch) -> None:
    from app.slices.calendar import routes

    monkeypatch.setattr(
        routes.funding_svc,
        "get_spending_class_choices",
        lambda: [("basic_needs", "Basic Needs")],
    )


def _make_project(*, title: str = "Route Test Project") -> Project:
    row = Project(
        project_title=title,
        status="draft_planning",
        funding_profile_key="ops_bridge_preapproved",
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


def _make_locked_snapshot(project_ulid: str, actor_ulid: str) -> dict:
    snapshot = create_working_snapshot(
        project_ulid=project_ulid,
        actor_ulid=actor_ulid,
        snapshot_label="Draft Basis",
        scope_summary="Phase 1",
    )
    add_budget_line(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=actor_ulid,
        label="Initial cost",
        line_kind="materials",
        estimated_total_cents=12000,
    )
    locked = lock_snapshot(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=actor_ulid,
    )
    db.session.flush()
    return locked


def _extract_tail_ulid(location: str) -> str:
    return location.rstrip("/").rsplit("/", 1)[-1]


def test_project_budget_workspace_renders(app, staff_client):
    with app.app_context():
        project = _make_project(title="Budget Workspace Project")
        project_ulid = project.ulid
        db.session.commit()

    resp = staff_client.get(f"/calendar/projects/{project_ulid}/budget")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Budget Workspace Project" in text
    assert "Budget" in text


def test_budget_routes_create_snapshot_add_line_and_lock(
    app,
    staff_client,
    monkeypatch,
):
    _patch_route_choices(monkeypatch)

    with app.app_context():
        project = _make_project(title="Budget Route Flow")
        task = _make_task(project.ulid, title="Assemble kits")
        project_ulid = project.ulid
        task_ulid = task.ulid
        db.session.commit()

    budget_path = f"/calendar/projects/{project_ulid}/budget"
    csrf = _get_csrf_token(staff_client, budget_path)

    resp = staff_client.post(
        f"/calendar/projects/{project_ulid}/budget/snapshots/new",
        data={
            "csrf_token": csrf,
            "snapshot_label": "Initial Estimate",
            "scope_summary": "Whole project",
            "assumptions_note": "Starting point",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        snapshot = db.session.execute(
            db.select(ProjectBudgetSnapshot).where(
                ProjectBudgetSnapshot.project_ulid == project_ulid,
                ProjectBudgetSnapshot.snapshot_label == "Initial Estimate",
            )
        ).scalar_one()
        assert snapshot.is_current is True
        snapshot_ulid = snapshot.ulid
        db.session.commit()
    csrf = _get_csrf_token(
        staff_client,
        f"/calendar/projects/{project_ulid}/budget?snapshot_ulid={snapshot_ulid}",
    )

    resp = staff_client.post(
        f"/calendar/projects/{project_ulid}/budget/"
        f"snapshots/{snapshot_ulid}/lines/new",
        data={
            "csrf_token": csrf,
            "task_ulid": task_ulid,
            "line_kind": "materials",
            "label": "Bedding pack",
            "detail": "Five starter kits",
            "basis_qty": 5,
            "basis_unit": "kits",
            "unit_cost_cents": 2500,
            "estimated_total_cents": 12500,
            "sort_order": 0,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        snapshot = db.session.get(ProjectBudgetSnapshot, snapshot_ulid)
        assert snapshot is not None
        assert snapshot.gross_cost_cents == 12500
        assert snapshot.expected_offset_cents == 0
        assert snapshot.net_need_cents == 12500
        lines = (
            db.session.execute(
                db.select(ProjectBudgetLine).where(
                    ProjectBudgetLine.budget_snapshot_ulid == snapshot_ulid
                )
            )
            .scalars()
            .all()
        )
        assert len(lines) == 1

    csrf = _get_csrf_token(
        staff_client,
        f"/calendar/projects/{project_ulid}/budget?snapshot_ulid={snapshot_ulid}",
    )

    resp = staff_client.post(
        f"/calendar/projects/{project_ulid}/budget/"
        f"snapshots/{snapshot_ulid}/lock",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        snapshot = db.session.get(ProjectBudgetSnapshot, snapshot_ulid)
        project = db.session.get(Project, project_ulid)
        assert snapshot is not None
        assert project is not None
        assert snapshot.is_locked is True
        assert project.status == "budget_ready"


def test_budget_line_create_route_rejects_late_add_after_lock(
    app,
    staff_client,
    monkeypatch,
):
    _patch_route_choices(monkeypatch)

    with app.app_context():
        project = _make_project(title="Locked Route Project")
        project_ulid = project.ulid
        snapshot = _make_locked_snapshot(
            project_ulid, actor_ulid=project_ulid
        )
        snapshot_ulid = snapshot["ulid"]
        db.session.commit()

    csrf = _get_csrf_token(
        staff_client,
        f"/calendar/projects/{project_ulid}/budget?snapshot_ulid={snapshot_ulid}",
    )

    resp = staff_client.post(
        f"/calendar/projects/{project_ulid}/budget/"
        f"snapshots/{snapshot_ulid}/lines/new",
        data={
            "csrf_token": csrf,
            "task_ulid": "",
            "line_kind": "materials",
            "label": "Late add",
            "estimated_total_cents": 100,
            "sort_order": 0,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        lines = (
            db.session.execute(
                db.select(ProjectBudgetLine).where(
                    ProjectBudgetLine.budget_snapshot_ulid == snapshot_ulid
                )
            )
            .scalars()
            .all()
        )
        assert len(lines) == 1
        assert lines[0].label == "Initial cost"


def test_demand_draft_new_page_renders_for_project(
    app,
    staff_client,
    monkeypatch,
):
    _patch_route_choices(monkeypatch)

    with app.app_context():
        project = _make_project(title="Draft New Page Project")
        project_ulid = project.ulid
        db.session.commit()

    resp = staff_client.get(
        f"/calendar/projects/{project_ulid}/demand-drafts/new"
        "?snapshot_ulid=01TESTTESTTESTTESTTESTTEST"
    )
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "New Demand Draft" in text
    assert "Draft New Page Project" in text


def test_demand_draft_create_route_rejects_unlocked_snapshot(
    app,
    staff_client,
    monkeypatch,
):
    _patch_governance_ok(monkeypatch)
    _patch_route_choices(monkeypatch)

    with app.app_context():
        project = _make_project(title="Unlocked Draft Route")
        snapshot = create_working_snapshot(
            project_ulid=project.ulid,
            actor_ulid=project.ulid,
            snapshot_label="Unlocked",
        )
        project_ulid = project.ulid
        snapshot_ulid = snapshot["ulid"]
        db.session.commit()

    new_path = (
        f"/calendar/projects/{project_ulid}/demand-drafts/new"
        f"?snapshot_ulid={snapshot_ulid}"
    )
    csrf = _get_csrf_token(staff_client, new_path)

    resp = staff_client.post(
        f"/calendar/projects/{project_ulid}/demand-drafts/new",
        data={
            "csrf_token": csrf,
            "snapshot_ulid": snapshot_ulid,
            "title": "Should fail",
            "summary": "This should not create.",
            "requested_amount_cents": 5000,
            "spending_class_candidate": "basic_needs",
            "source_profile_key": "ops_bridge_preapproved",
            "tag_any": "housing,kit",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400

    with app.app_context():
        rows = (
            db.session.execute(
                db.select(DemandDraft).where(
                    DemandDraft.project_ulid == project_ulid
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


def test_demand_draft_route_lifecycle_promotes_to_funding_demand(
    app,
    staff_client,
    admin_client,
    monkeypatch,
):
    _patch_governance_ok(monkeypatch)
    _patch_route_choices(monkeypatch)

    with app.app_context():
        project = _make_project(title="Draft Route Lifecycle")
        project_ulid = project.ulid
        snapshot = _make_locked_snapshot(
            project_ulid, actor_ulid=project_ulid
        )
        snapshot_ulid = snapshot["ulid"]
        db.session.commit()

    new_path = (
        f"/calendar/projects/{project_ulid}/demand-drafts/new"
        f"?snapshot_ulid={snapshot_ulid}"
    )
    csrf = _get_csrf_token(staff_client, new_path)

    resp = staff_client.post(
        f"/calendar/projects/{project_ulid}/demand-drafts/new",
        data={
            "csrf_token": csrf,
            "snapshot_ulid": snapshot_ulid,
            "title": "Welcome Home Ask",
            "summary": "Initial version",
            "scope_summary": "Phase 1",
            "requested_amount_cents": 12000,
            "spending_class_candidate": "basic_needs",
            "source_profile_key": "ops_bridge_preapproved",
            "tag_any": "welcome_home_kit, furniture",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    draft_ulid = _extract_tail_ulid(resp.headers["Location"])

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(staff_client, detail_path)

    resp = staff_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/ready",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(staff_client, detail_path)

    resp = staff_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/submit",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(admin_client, detail_path)

    # Demand draft return is an Admin-only governance review action.
    # Staff owns drafting and submission; Admin owns review return.
    resp = admin_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/return",
        data={
            "note": "Tighten the narrative and source posture.",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(admin_client, detail_path)
    # Approval is also part of the Admin/governance review surface.
    resp = admin_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/edit",
        data={
            "csrf_token": csrf,
            "snapshot_ulid": snapshot_ulid,
            "title": "Revised Ask",
            "summary": "Revised version",
            "scope_summary": "Phase 1",
            "requested_amount_cents": 12000,
            "spending_class_candidate": "basic_needs",
            "source_profile_key": ("grant_return_unused"),
            "tag_any": "welcome_home_kit, furniture",
            "governance_note": "Addressed review comments.",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(staff_client, detail_path)

    resp = staff_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/ready",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(staff_client, detail_path)

    resp = staff_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/submit",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(staff_client, detail_path)

    resp = staff_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/approve",
        data={
            "csrf_token": csrf,
            "spending_class": "basic_needs",
            "source_profile_key": ("grant_return_unused"),
            "tag_any": "welcome_home_kit, furniture",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    detail_path = f"/calendar/demand-drafts/{draft_ulid}"
    csrf = _get_csrf_token(admin_client, detail_path)

    # Promote publishes the reviewed demand into FundingDemand.
    resp = admin_client.post(
        f"/calendar/demand-drafts/{draft_ulid}/promote",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    funding_ulid = _extract_tail_ulid(resp.headers["Location"])

    with app.app_context():
        draft = db.session.get(DemandDraft, draft_ulid)
        funding = db.session.get(FundingDemand, funding_ulid)
        assert draft is not None
        assert funding is not None
        assert draft.status == "approved_for_publish"
        assert draft.promoted_at_utc is not None
        assert funding.status == "published"
        assert funding.goal_cents == 12000
        assert funding.origin_draft_ulid == draft_ulid
        assert funding.project_ulid == project_ulid
        assert (
            funding.published_context_json["origin"]["budget_snapshot_ulid"]
            == snapshot_ulid
        )
