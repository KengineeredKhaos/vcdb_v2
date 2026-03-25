# tests/slices/sponsors/test_sponsors_routes_funding_matches.py

from __future__ import annotations

from app.extensions import db
from app.slices.calendar.models import Project
from app.slices.calendar.models import Project, Task
from app.slices.calendar.services_funding import (
    create_funding_demand,
    publish_funding_demand,
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
) -> str:
    project = Project(
        project_title=f"{title} Project",
        status="planned",
    )
    db.session.add(project)
    db.session.flush()

    row = create_funding_demand(
        {
            "project_ulid": project.ulid,
            "title": title,
            "goal_cents": 25000,
            "deadline_date": "2026-04-15",
            "spending_class": spending_class,
            "tag_any": tag_any,
        },
        actor_ulid=None,
        request_id=f"req-route-match-create-{title}",
    )
    db.session.flush()

    row = publish_funding_demand(
        row.ulid,
        actor_ulid=None,
        request_id=f"req-route-match-publish-{title}",
    )
    db.session.flush()
    return row.ulid


def test_funding_opportunity_detail_shows_sponsor_matches(
    app, staff_client, monkeypatch
):
    from app.slices.calendar import services_funding as cal_svc

    monkeypatch.setattr(
        cal_svc,
        "_project_policy_hints",
        lambda project_ulid: cal_svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        demand_ulid = _create_published_demand(
            title="Route Match Demand",
            spending_class="basic_needs",
            tag_any="crm_seed",
        )
        sponsor = _create_sponsor("Route Match Sponsor")

        out1 = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": True,
                "mission_basic_needs": True,
                "style_cash_grant": True,
                "relationship_prior_success": True,
                "restriction_geo_local_only": True,
                "restriction_population_veterans_only": True,
            },
            actor_ulid=None,
            request_id="req-route-match-1",
        )
        db.session.flush()
        assert out1 is not None

        out2 = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_note": "Warm history with veteran-focused asks.",
            },
            actor_ulid=None,
            request_id="req-route-match-2",
        )
        db.session.flush()
        assert out2 is not None

        db.session.commit()

    resp = staff_client.get(f"/sponsors/funding-opportunities/{demand_ulid}")
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "Sponsor opportunity matches" in text
    assert sponsor.entity_ulid in text
    assert "likely_fit" in text
    assert "proceed_outreach" in text
    assert "Positive signals" in text
    assert "Profile note hints" in text
    assert "Warm history with veteran-focused asks." in text
    assert "Current cultivation" in text
    assert "View sponsor dossier" in text
    assert "Review CRM posture" in text



def test_funding_opportunity_detail_shows_recent_cultivation_for_demand(
    app, staff_client, monkeypatch
):
    from app.slices.calendar import services_funding as cal_svc
    from app.slices.sponsors.services_calendar import ensure_cultivation_project

    monkeypatch.setattr(
        cal_svc,
        "_project_policy_hints",
        lambda project_ulid: cal_svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        demand_ulid = _create_published_demand(
            title="Route Demand Activity",
            spending_class="basic_needs",
            tag_any="crm_seed",
        )
        sponsor = _create_sponsor("Demand Activity Route Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=sponsor.entity_ulid,
            request_id="req-route-demand-activity-1",
        )
        task = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: Demand Activity Route Sponsor",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-24T18:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "outcome": {
                    "outcome_note": "Interested in the current ask.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": False,
                    "funding_interest_signal": True,
                },
            },
        )
        db.session.add(task)
        db.session.commit()

    resp = staff_client.get(f"/sponsors/funding-opportunities/{demand_ulid}")
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "Recent cultivation for this demand" in text
    assert "Demand Activity Route Sponsor" in text
    assert "Interested in the current ask." in text
    assert "Funding interest surfaced" in text
    assert "Follow-up recommended" in text
    assert "Follow-up pending review" in text
    assert "View sponsor dossier" in text
    assert "Review CRM posture" in text
