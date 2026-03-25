# tests/slices/sponsors/test_sponsors_services_calendar_follow_up.py

from __future__ import annotations

from app.extensions import db
from app.slices.calendar.models import Task
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_calendar import (
    create_follow_up_cultivation_task,
    ensure_cultivation_project,
)


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


def test_create_follow_up_cultivation_task_carries_context(app, ulid):
    with app.app_context():
        actor_ulid = ulid()
        db.session.add(Entity(ulid=actor_ulid, kind="person"))
        db.session.flush()

        sponsor = _create_sponsor("Follow Up Service Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-follow-up-service-1",
        )

        prior = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: Follow Up Service Sponsor",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-24T23:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": "01EEEEEEEEEEEEEEEEEEEEEEEE",
                "outcome": {
                    "outcome_note": "Asked for a two-paragraph summary.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": False,
                    "funding_interest_signal": True,
                },
            },
        )
        db.session.add(prior)
        db.session.flush()

        created = create_follow_up_cultivation_task(
            sponsor_entity_ulid=sponsor.entity_ulid,
            task_ulid=prior.ulid,
            actor_ulid=actor_ulid,
            request_id="req-follow-up-service-2",
            assigned_to_ulid=actor_ulid,
        )
        db.session.commit()

        task = db.session.get(Task, created["ulid"])
        assert task is not None
        assert task.task_title == (
            "Follow up with sponsor: Follow Up Service Sponsor"
        )
        assert task.requirements_json["sponsor_entity_ulid"] == (
            sponsor.entity_ulid
        )
        assert task.requirements_json["funding_demand_ulid"] == (
            "01EEEEEEEEEEEEEEEEEEEEEEEE"
        )
        assert task.requirements_json["follow_up_for_task_ulid"] == (
            prior.ulid
        )
        assert (
            task.requirements_json["follow_up_source"]["outcome_note"]
            == "Asked for a two-paragraph summary."
        )
        assert "Prior task:" in (task.task_detail or "")
        assert "Prior outcome note:" in (task.task_detail or "")
