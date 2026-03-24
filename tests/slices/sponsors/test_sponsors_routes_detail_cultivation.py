# tests/slices/sponsors/test_sponsors_routes_detail_cultivation.py

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


def test_sponsor_detail_page_shows_recent_cultivation_activity(
    app, staff_client, ulid
):
    with app.app_context():
        actor_ulid = ulid()
        db.session.add(Entity(ulid=actor_ulid, kind="person"))
        db.session.flush()

        sponsor = _create_sponsor("Cultivation Detail Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-detail-cultivation-1",
        )

        db.session.add(
            Task(
                project_ulid=project["ulid"],
                task_title="Cultivate sponsor: Cultivation Detail Sponsor",
                task_kind="fundraising_cultivation",
                status="done",
                done_at_utc="2026-03-24T20:00:00Z",
                requirements_json={
                    "source_slice": "sponsors",
                    "workflow": "cultivation",
                    "sponsor_entity_ulid": sponsor.entity_ulid,
                    "funding_demand_ulid": "01BBBBBBBBBBBBBBBBBBBBBBBB",
                    "outcome": {
                        "outcome_note": "Asked for a short write-up next week.",
                        "follow_up_recommended": True,
                        "off_cadence_follow_up_signal": True,
                        "funding_interest_signal": False,
                    },
                },
            )
        )
        db.session.commit()

    resp = staff_client.get(f"/sponsors/{sponsor.entity_ulid}/detail")
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "Recent cultivation activity" in text
    assert "Cultivate sponsor: Cultivation Detail Sponsor" in text
    assert "Asked for a short write-up next week." in text
    assert "Follow-up: yes" in text
    assert "Off cadence: yes" in text
    assert "Funding interest: no" in text
