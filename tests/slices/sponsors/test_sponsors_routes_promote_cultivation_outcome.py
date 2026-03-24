# tests/slices/sponsors/test_sponsors_routes_promote_cultivation_outcome.py

from __future__ import annotations

from app.extensions import db
from app.slices.calendar.models import Task
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services import get_profile_hints
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


def test_promote_cultivation_outcome_to_relationship_note(
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
        sponsor = _create_sponsor("Promote Outcome Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-promote-outcome-1",
        )

        task = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: Promote Outcome Sponsor",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-24T21:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": "01CCCCCCCCCCCCCCCCCCCCCCCC",
                "outcome": {
                    "outcome_note": "Asked for a short project summary next week.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": True,
                    "funding_interest_signal": True,
                },
            },
        )
        db.session.add(task)
        db.session.commit()
        task_ulid = task.ulid
        sponsor_ulid = sponsor.entity_ulid

    resp = staff_client.post(
        f"/sponsors/{sponsor_ulid}/cultivation-outcomes/{task_ulid}/promote-relationship-note",
        data={
            "next": f"/sponsors/{sponsor_ulid}/detail",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "Outcome note promoted to relationship note." in text

    with app.app_context():
        hints = get_profile_hints(sponsor_ulid)
        relationship_note = hints.get("relationship_note") or ""

        assert (
            "Cultivation outcome — Cultivate sponsor: Promote Outcome Sponsor"
            in relationship_note
        )
        assert "Completed: 2026-03-24T21:00:00Z" in relationship_note
        assert "Demand: 01CCCCCCCCCCCCCCCCCCCCCCCC" in relationship_note
        assert (
            "Asked for a short project summary next week."
            in relationship_note
        )


def test_promote_cultivation_outcome_to_relationship_note_is_idempotent(
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
        sponsor = _create_sponsor("Promote Outcome Noop Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-promote-outcome-noop-1",
        )

        task = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: Promote Outcome Noop Sponsor",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-24T22:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": "01DDDDDDDDDDDDDDDDDDDDDDDD",
                "outcome": {
                    "outcome_note": "Interested in a one-page project summary.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": False,
                    "funding_interest_signal": True,
                },
            },
        )
        db.session.add(task)
        db.session.commit()

        task_ulid = task.ulid
        sponsor_ulid = sponsor.entity_ulid

    resp1 = staff_client.post(
        f"/sponsors/{sponsor_ulid}/cultivation-outcomes/{task_ulid}/promote-relationship-note",
        data={"next": f"/sponsors/{sponsor_ulid}/detail"},
        follow_redirects=True,
    )
    assert resp1.status_code == 200
    assert "Outcome note promoted to relationship note." in resp1.get_data(
        as_text=True
    )

    with app.app_context():
        hints1 = get_profile_hints(sponsor_ulid)
        relationship_note_1 = hints1.get("relationship_note") or ""

    resp2 = staff_client.post(
        f"/sponsors/{sponsor_ulid}/cultivation-outcomes/{task_ulid}/promote-relationship-note",
        data={"next": f"/sponsors/{sponsor_ulid}/detail"},
        follow_redirects=True,
    )
    assert resp2.status_code == 200
    assert "No relationship note change." in resp2.get_data(as_text=True)

    with app.app_context():
        hints2 = get_profile_hints(sponsor_ulid)
        relationship_note_2 = hints2.get("relationship_note") or ""

    assert relationship_note_2 == relationship_note_1
    assert (
        relationship_note_2.count(
            "Cultivation outcome — Cultivate sponsor: Promote Outcome Noop Sponsor"
        )
        == 1
    )
    assert (
        relationship_note_2.count("Interested in a one-page project summary.")
        == 1
    )
