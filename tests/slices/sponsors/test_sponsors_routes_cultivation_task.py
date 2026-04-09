# tests/slices/sponsors/test_sponsors_routes_cultivation_task.py

from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import governance_v2
from app.slices.calendar.models import Project, Task
from app.slices.calendar.services_budget import (
    add_budget_line,
    create_working_snapshot,
    lock_snapshot,
)
from app.slices.calendar.services_drafts import (
    approve_draft_for_publish,
    create_draft_from_snapshot,
    mark_draft_ready_for_review,
    promote_draft_to_funding_demand,
    submit_draft_for_governance_review,
)
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services import set_profile_hints
from app.slices.sponsors.services_crm import set_crm_factors


def _create_sponsor(name: str) -> Sponsor:
    entity = Entity(kind="org")
    db.session.add(entity)
    db.session.flush()

    db.session.add(
        EntityOrg(
            entity_ulid=entity.ulid,
            legal_name=name,
        )
    )

    sponsor = Sponsor(entity_ulid=entity.ulid)
    db.session.add(sponsor)
    db.session.flush()
    return sponsor


def _create_published_demand(
    *,
    title: str,
    spending_class: str,
    tag_any: str,
    source_profile_key: str = "mission_local_veterans_cash",
    default_restriction_keys: tuple[str, ...] = (
        "local_only",
        "vet_only",
    ),
    eligible_fund_codes: tuple[str, ...] = ("general_unrestricted",),
) -> str:
    project = Project(
        project_title=f"{title} Project",
        status="draft_planning",
        funding_profile_key=source_profile_key,
    )
    db.session.add(project)
    db.session.flush()

    snapshot = create_working_snapshot(
        project_ulid=project.ulid,
        actor_ulid=project.ulid,
        snapshot_label=f"{title} Basis",
        scope_summary=title,
    )
    add_budget_line(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=project.ulid,
        label="Initial cost",
        line_kind="materials",
        estimated_total_cents=25000,
    )
    locked = lock_snapshot(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=project.ulid,
    )
    db.session.flush()

    draft = create_draft_from_snapshot(
        project_ulid=project.ulid,
        snapshot_ulid=locked["ulid"],
        actor_ulid=project.ulid,
        title=title,
        summary=f"{title} summary",
        scope_summary=title,
        requested_amount_cents=25000,
        spending_class_candidate=spending_class,
        source_profile_key=source_profile_key,
        tag_any=tag_any,
    )
    draft = mark_draft_ready_for_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    draft = submit_draft_for_governance_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    draft = approve_draft_for_publish(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
        governance_decision=governance_v2.GovernanceReviewDecisionDTO(
            decision="approved",
            governance_note="Governance semantics approved for publish.",
            approved_spending_class=spending_class,
            approved_source_profile_key=source_profile_key,
            eligible_fund_codes=tuple(eligible_fund_codes),
            default_restriction_keys=tuple(default_restriction_keys),
            approved_tag_any=tuple(
                part.strip()
                for part in str(tag_any or "").split(",")
                if part.strip()
            ),
            decision_fingerprint="fp-cultivation-route",
            validation_errors=(),
            reason_codes=(),
            matched_rule_ids=(),
        ),
    )
    promoted = promote_draft_to_funding_demand(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    db.session.flush()
    return promoted["funding_demand"]["funding_demand_ulid"]


def test_create_cultivation_task_from_opportunity_match(
    app, staff_client, monkeypatch, ulid
):
    with app.app_context():
        actor_ulid = ulid()
        db.session.add(Entity(ulid=actor_ulid, kind="person"))
        db.session.commit()

    monkeypatch.setattr(
        "app.slices.sponsors.routes._actor_ulid",
        lambda: actor_ulid,
    )

    with app.app_context():
        demand_ulid = _create_published_demand(
            title="Cultivation Match Demand",
            spending_class="basic_needs",
            tag_any="crm_seed",
        )
        sponsor = _create_sponsor("Cultivation Sponsor")

        out1 = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": True,
                "mission_basic_needs": True,
                "style_cash_grant": True,
                "relationship_prior_success": True,
            },
            actor_ulid=None,
            request_id="req-cultivation-1",
        )
        db.session.flush()
        assert out1 is not None

        out2 = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_note": "Warm history with veteran-focused asks.",
            },
            actor_ulid=None,
            request_id="req-cultivation-2",
        )
        db.session.flush()
        assert out2 is not None

        db.session.commit()

    with app.app_context():
        projects_before = (
            db.session.query(Project)
            .filter(Project.project_title == "Sponsor Cultivation")
            .all()
        )
        tasks_before = (
            db.session.query(Task)
            .filter(Task.task_kind == "fundraising_cultivation")
            .all()
        )
        before_task_count = len(tasks_before)
        before_project_count = len(projects_before)

    resp = staff_client.post(
        f"/sponsors/{sponsor.entity_ulid}/cultivation-task",
        data={
            "funding_demand_ulid": demand_ulid,
            "next": f"/sponsors/funding-opportunities/{demand_ulid}",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "Cultivation task created:" in text

    with app.app_context():
        projects_after = (
            db.session.query(Project)
            .filter(Project.project_title == "Sponsor Cultivation")
            .all()
        )
        tasks_after = (
            db.session.query(Task)
            .filter(Task.task_kind == "fundraising_cultivation")
            .order_by(Task.created_at_utc.asc())
            .all()
        )

        if before_project_count == 0:
            assert len(projects_after) == 1
        else:
            assert len(projects_after) == before_project_count

        created = [
            row
            for row in tasks_after
            if isinstance(row.requirements_json, dict)
            and row.requirements_json.get("sponsor_entity_ulid")
            == sponsor.entity_ulid
            and row.requirements_json.get("funding_demand_ulid")
            == demand_ulid
        ]

        assert len(tasks_after) == before_task_count + 1
        assert created

        task = created[-1]
        assert task.project_ulid == projects_after[0].ulid
        assert task.task_kind == "fundraising_cultivation"
        assert "Cultivate sponsor:" in task.task_title
        assert (
            sponsor.entity_ulid
            == task.requirements_json["sponsor_entity_ulid"]
        )
        assert demand_ulid == task.requirements_json["funding_demand_ulid"]
        assert task.requirements_json["match"]["fit_band"] in {
            "likely_fit",
            "maybe_fit",
            "caution",
        }


def test_cultivation_project_is_reused(app, staff_client, monkeypatch, ulid):
    with app.app_context():
        actor_ulid = ulid()
        db.session.add(Entity(ulid=actor_ulid, kind="person"))
        db.session.commit()

    monkeypatch.setattr(
        "app.slices.sponsors.routes._actor_ulid",
        lambda: actor_ulid,
    )

    with app.app_context():
        sponsor = _create_sponsor("Reusable Cultivation Sponsor")
        db.session.commit()

    resp1 = staff_client.post(
        f"/sponsors/{sponsor.entity_ulid}/cultivation-task",
        data={"next": f"/sponsors/{sponsor.entity_ulid}/detail"},
        follow_redirects=True,
    )
    assert resp1.status_code == 200

    with app.app_context():
        projects_after_first = (
            db.session.query(Project)
            .filter(Project.project_title == "Sponsor Cultivation")
            .all()
        )
        tasks_after_first = db.session.query(Task).all()

        assert len(projects_after_first) == 1
        first_task_count = len(tasks_after_first)

    resp2 = staff_client.post(
        f"/sponsors/{sponsor.entity_ulid}/cultivation-task",
        data={"next": f"/sponsors/{sponsor.entity_ulid}/detail"},
        follow_redirects=True,
    )
    assert resp2.status_code == 200

    with app.app_context():
        projects_after_second = (
            db.session.query(Project)
            .filter(Project.project_title == "Sponsor Cultivation")
            .all()
        )
        tasks_after_second = db.session.query(Task).all()

        assert len(projects_after_second) == 1
        assert len(tasks_after_second) == first_task_count + 1
