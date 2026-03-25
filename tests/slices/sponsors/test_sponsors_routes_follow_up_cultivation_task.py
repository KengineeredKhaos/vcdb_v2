# tests/slices/sponsors/test_sponsors_routes_follow_up_cultivation_task.py

from __future__ import annotations

from app.extensions import db
from app.slices.calendar.models import Task
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_calendar import ensure_cultivation_project


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


def test_create_follow_up_cultivation_task_route(
    app, staff_client, monkeypatch, ulid
):
    with app.app_context():
        actor_ulid = ulid()
        demand_ulid = ulid()
        db.session.add(Entity(ulid=actor_ulid, kind="person"))
        db.session.commit()

    monkeypatch.setattr(
        "app.slices.sponsors.routes._actor_ulid",
        lambda: actor_ulid,
    )

    with app.app_context():
        sponsor = _create_sponsor("Follow Up Route Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-follow-up-route-1",
        )

        prior = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: Follow Up Route Sponsor",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-24T23:30:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "outcome": {
                    "outcome_note": "Requested a short call next Tuesday.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": True,
                    "funding_interest_signal": False,
                },
            },
        )
        db.session.add(prior)
        db.session.commit()
        task_ulid = prior.ulid
        sponsor_ulid = sponsor.entity_ulid

        before_count = db.session.query(Task).count()

    resp = staff_client.post(
        f"/sponsors/{sponsor_ulid}/cultivation-outcomes/{task_ulid}/follow-up-task",
        data={"next": f"/sponsors/{sponsor_ulid}/detail"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Follow-up cultivation task created:" in resp.get_data(
        as_text=True
    )

    with app.app_context():
        tasks = (
            db.session.query(Task).order_by(Task.created_at_utc.asc()).all()
        )
        assert len(tasks) == before_count + 1

        created = [
            row
            for row in tasks
            if isinstance(row.requirements_json, dict)
            and row.requirements_json.get("follow_up_for_task_ulid")
            == task_ulid
        ]
        assert len(created) == 1

        task = created[0]
        assert task.requirements_json["follow_up_for_task_ulid"] == task_ulid
        assert task.requirements_json["funding_demand_ulid"] == (demand_ulid)
        assert (
            task.requirements_json["follow_up_source"][
                "follow_up_recommended"
            ]
            is True
        )
        assert (
            task.requirements_json["follow_up_source"][
                "off_cadence_follow_up_signal"
            ]
            is True
        )


def test_follow_up_task_route_rejects_wrong_sponsor(
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
        sponsor = _create_sponsor("Follow Up Correct Sponsor")
        other = _create_sponsor("Follow Up Wrong Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-follow-up-route-2",
        )

        prior = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: Follow Up Correct Sponsor",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-25T00:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "outcome": {
                    "outcome_note": "Requested a short written summary.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": False,
                    "funding_interest_signal": True,
                },
            },
        )
        db.session.add(prior)
        db.session.commit()
        task_ulid = prior.ulid
        other_ulid = other.entity_ulid
        before_count = db.session.query(Task).count()

    resp = staff_client.post(
        f"/sponsors/{other_ulid}/cultivation-outcomes/{task_ulid}/follow-up-task",
        data={"next": f"/sponsors/{other_ulid}/detail"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "cultivation outcome does not belong to sponsor" in resp.get_data(
        as_text=True
    )

    with app.app_context():
        after_count = db.session.query(Task).count()
        assert after_count == before_count
