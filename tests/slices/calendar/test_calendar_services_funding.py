# tests/slices/calendar/test_calendar_services_funding.py

from __future__ import annotations

from app.extensions import db
from app.slices.calendar.models import Project
from app.slices.calendar.services_funding import (
    create_funding_demand,
    publish_funding_demand,
    unpublish_funding_demand,
)


def test_create_publish_unpublish_funding_demand(app):
    with app.app_context():
        project = Project(
            project_title="Test Project",
            status="planned",
        )
        db.session.add(project)
        db.session.commit()

        row = create_funding_demand(
            {
                "project_ulid": project.ulid,
                "title": "Kitchen starter kit",
                "goal_cents": 12000,
                "deadline_date": "2026-03-31",
                "spending_class": "admin",
                "tag_any": "",
            },
            actor_ulid=None,
            request_id="req-test-1",
        )
        db.session.commit()

        assert row.status == "draft"
        assert row.goal_cents == 12000
        assert row.project_ulid == project.ulid

        row = publish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-test-2",
        )
        db.session.commit()

        assert row.status == "published"
        assert row.published_at_utc is not None
        assert isinstance(row.eligible_fund_keys_json, list)

        row = unpublish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-test-3",
        )
        db.session.commit()

        assert row.status == "draft"
        assert row.published_at_utc is None
