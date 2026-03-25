# tests/slices/sponsors/test_sponsors_services_calendar_outcomes.py

from __future__ import annotations

from app.extensions import db
from app.slices.calendar.models import Project, Task
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_calendar import (
    ensure_cultivation_project,
    list_recent_cultivation_activity_for_demand,
    list_recent_cultivation_outcomes,
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


def test_list_recent_cultivation_outcomes_reads_signals(app, ulid):
    with app.app_context():
        actor_ulid = ulid()
        db.session.add(Entity(ulid=actor_ulid, kind="person"))
        db.session.flush()

        sponsor = _create_sponsor("Outcome Reader Sponsor")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-outcome-reader-1",
        )

        demand_ulid = ulid()

        task = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: Outcome Reader Sponsor",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-24T18:00:00Z",
            notes="General task note.",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "outcome": {
                    "outcome_note": "Interested in housing-related support.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": True,
                    "funding_interest_signal": True,
                },
            },
        )
        db.session.add(task)
        db.session.commit()

        rows = list_recent_cultivation_outcomes(
            sponsor.entity_ulid,
            limit=10,
        )

        assert len(rows) == 1
        row = rows[0]
        assert row.sponsor_entity_ulid == sponsor.entity_ulid
        assert row.workflow == "cultivation"
        assert row.status == "done"
        assert row.funding_demand_ulid == demand_ulid
        assert row.outcome_note == "Interested in housing-related support."
        assert row.follow_up_recommended is True
        assert row.off_cadence_follow_up_signal is True
        assert row.funding_interest_signal is True



def test_list_recent_cultivation_activity_for_demand_latest_per_sponsor(
    app, ulid
):
    with app.app_context():
        actor_ulid = ulid()
        db.session.add(Entity(ulid=actor_ulid, kind="person"))
        db.session.flush()

        sponsor_a = _create_sponsor("Demand Activity Sponsor A")
        sponsor_b = _create_sponsor("Demand Activity Sponsor B")

        project = ensure_cultivation_project(
            actor_ulid=actor_ulid,
            request_id="req-demand-activity-1",
        )

        demand_ulid = ulid()

        older = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: older touch",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-20T18:00:00Z",
            created_at_utc="2026-03-20T18:00:00Z",
            updated_at_utc="2026-03-20T18:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor_a.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "outcome": {
                    "outcome_note": "Older note.",
                    "follow_up_recommended": False,
                    "off_cadence_follow_up_signal": False,
                    "funding_interest_signal": False,
                },
            },
        )
        newer = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: latest touch",
            task_kind="fundraising_cultivation",
            status="done",
            done_at_utc="2026-03-24T18:00:00Z",
            created_at_utc="2026-03-24T18:00:00Z",
            updated_at_utc="2026-03-24T18:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor_a.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "outcome": {
                    "outcome_note": "Latest note.",
                    "follow_up_recommended": True,
                    "off_cadence_follow_up_signal": False,
                    "funding_interest_signal": True,
                },
            },
        )
        open_task = Task(
            project_ulid=project["ulid"],
            task_title="Cultivate sponsor: scheduled follow-up",
            task_kind="fundraising_cultivation",
            status="planned",
            due_at_utc="2026-03-28T18:00:00Z",
            created_at_utc="2026-03-25T18:00:00Z",
            updated_at_utc="2026-03-25T18:00:00Z",
            requirements_json={
                "source_slice": "sponsors",
                "workflow": "cultivation",
                "sponsor_entity_ulid": sponsor_b.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "outcome": {
                    "outcome_note": None,
                    "follow_up_recommended": False,
                    "off_cadence_follow_up_signal": False,
                    "funding_interest_signal": False,
                },
            },
        )
        db.session.add_all([older, newer, open_task])
        db.session.commit()

        rows = list_recent_cultivation_activity_for_demand(
            demand_ulid,
            limit=20,
        )

        assert len(rows) == 2
        assert rows[0].sponsor_entity_ulid == sponsor_b.entity_ulid
        assert rows[0].follow_up_status == "follow_up_scheduled"
        assert rows[1].sponsor_entity_ulid == sponsor_a.entity_ulid
        assert rows[1].task_title == "Cultivate sponsor: latest touch"
        assert rows[1].outcome_note == "Latest note."
        assert rows[1].funding_interest_signal is True
        assert rows[1].follow_up_status == "follow_up_pending_review"
