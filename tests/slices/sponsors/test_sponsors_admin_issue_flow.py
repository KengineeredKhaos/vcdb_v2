# tests/slices/sponsors/test_sponsors_admin_issue_flow.py

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.slices.admin.models import AdminAlert
from app.slices.entity.models import EntityPerson
from app.slices.sponsors import admin_issue_services as issue_svc
from app.slices.sponsors import onboard_services as wiz
from app.slices.sponsors.models import Sponsor, SponsorAdminIssue
from tests.support.real_auth import seed_real_auth_world


@pytest.fixture()
def sponsor_seeded(app):
    seed_real_auth_world(
        app,
        customers=0,
        resources=0,
        sponsors=1,
        normalize_passwords=False,
    )
    return app


def _first_sponsor_entity_ulid(app) -> str:
    with app.app_context():
        value = (
            db.session.execute(
                select(Sponsor.entity_ulid).order_by(Sponsor.entity_ulid)
            )
            .scalars()
            .first()
        )
    assert value, "Expected at least one seeded sponsor"
    return str(value)


def _first_person_entity_ulid(app) -> str:
    with app.app_context():
        value = (
            db.session.execute(
                select(EntityPerson.entity_ulid).order_by(
                    EntityPerson.entity_ulid
                )
            )
            .scalars()
            .first()
        )
    assert value, "Expected at least one seeded person"
    return str(value)


def _clear_issue_tables() -> None:
    db.session.query(AdminAlert).delete()
    db.session.query(SponsorAdminIssue).delete()
    db.session.commit()


def test_submit_onboard_admin_issue_marks_complete_and_raises_alert(
    sponsor_seeded,
):
    sponsor_ulid = _first_sponsor_entity_ulid(sponsor_seeded)
    actor_ulid = _first_person_entity_ulid(sponsor_seeded)

    with sponsor_seeded.app_context():
        _clear_issue_tables()

        receipt = wiz.submit_onboard_admin_issue(
            entity_ulid=sponsor_ulid,
            request_id="req-sponsors-onboard-001",
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        sponsor = db.session.get(Sponsor, sponsor_ulid)
        issue = db.session.execute(
            select(SponsorAdminIssue).where(
                SponsorAdminIssue.request_id == "req-sponsors-onboard-001",
                SponsorAdminIssue.target_ulid == sponsor_ulid,
                SponsorAdminIssue.reason_code == "advisory_sponsors_onboard",
            )
        ).scalar_one()

        alert = db.session.execute(
            select(AdminAlert).where(
                AdminAlert.request_id == "req-sponsors-onboard-001",
                AdminAlert.target_ulid == sponsor_ulid,
                AdminAlert.reason_code == "advisory_sponsors_onboard",
            )
        ).scalar_one()

        assert receipt.alert_ulid == alert.ulid
        assert sponsor is not None
        assert sponsor.onboard_step == "complete"

        assert issue.source_status == "pending_review"
        assert issue.closed_at_utc is None

        assert alert.source_slice == "sponsors"
        assert alert.admin_status == "open"
        assert alert.workflow_key == "sponsors_onboard_issue"


def test_raise_onboard_admin_issue_is_idempotent_for_same_request(
    sponsor_seeded,
):
    sponsor_ulid = _first_sponsor_entity_ulid(sponsor_seeded)
    actor_ulid = _first_person_entity_ulid(sponsor_seeded)

    with sponsor_seeded.app_context():
        _clear_issue_tables()

        first = issue_svc.raise_onboard_admin_issue(
            entity_ulid=sponsor_ulid,
            request_id="req-sponsors-onboard-002",
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        second = issue_svc.raise_onboard_admin_issue(
            entity_ulid=sponsor_ulid,
            request_id="req-sponsors-onboard-002",
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        issues = db.session.execute(select(SponsorAdminIssue)).scalars().all()
        alerts = db.session.execute(select(AdminAlert)).scalars().all()

        assert len(issues) == 1
        assert len(alerts) == 1
        assert first.alert_ulid == second.alert_ulid


def test_resolve_onboard_admin_issue_approve_closes_alert_and_activates_sponsor(
    sponsor_seeded,
):
    sponsor_ulid = _first_sponsor_entity_ulid(sponsor_seeded)
    actor_ulid = _first_person_entity_ulid(sponsor_seeded)

    with sponsor_seeded.app_context():
        _clear_issue_tables()

        issue_svc.raise_onboard_admin_issue(
            entity_ulid=sponsor_ulid,
            request_id="req-sponsors-onboard-003",
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        issue = db.session.execute(
            select(SponsorAdminIssue).where(
                SponsorAdminIssue.request_id == "req-sponsors-onboard-003",
                SponsorAdminIssue.target_ulid == sponsor_ulid,
                SponsorAdminIssue.reason_code == "advisory_sponsors_onboard",
            )
        ).scalar_one()

        receipt = issue_svc.resolve_onboard_admin_issue(
            issue_ulid=issue.ulid,
            decision="approve",
            actor_ulid=actor_ulid,
            request_id="req-sponsors-onboard-003",
        )
        db.session.commit()

        sponsor = db.session.get(Sponsor, sponsor_ulid)
        issue = db.session.get(SponsorAdminIssue, issue.ulid)
        alert = db.session.execute(
            select(AdminAlert).where(
                AdminAlert.request_id == "req-sponsors-onboard-003",
                AdminAlert.target_ulid == sponsor_ulid,
                AdminAlert.reason_code == "advisory_sponsors_onboard",
            )
        ).scalar_one()

        assert receipt is not None
        assert sponsor is not None
        assert sponsor.readiness_status == "active"
        assert sponsor.admin_review_required is False

        assert issue.source_status == "approved"
        assert issue.closed_at_utc is not None

        assert alert.admin_status == "resolved"
        assert alert.source_status == "approved"
        assert alert.close_reason == "approved_in_sponsors"
        assert alert.closed_at_utc is not None


def test_resolve_onboard_admin_issue_reject_closes_alert_and_keeps_draft(
    sponsor_seeded,
):
    sponsor_ulid = _first_sponsor_entity_ulid(sponsor_seeded)
    actor_ulid = _first_person_entity_ulid(sponsor_seeded)

    with sponsor_seeded.app_context():
        _clear_issue_tables()

        issue_svc.raise_onboard_admin_issue(
            entity_ulid=sponsor_ulid,
            request_id="req-sponsors-onboard-004",
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        issue = db.session.execute(
            select(SponsorAdminIssue).where(
                SponsorAdminIssue.request_id == "req-sponsors-onboard-004",
                SponsorAdminIssue.target_ulid == sponsor_ulid,
                SponsorAdminIssue.reason_code == "advisory_sponsors_onboard",
            )
        ).scalar_one()

        receipt = issue_svc.resolve_onboard_admin_issue(
            issue_ulid=issue.ulid,
            decision="reject",
            actor_ulid=actor_ulid,
            request_id="req-sponsors-onboard-004",
        )
        db.session.commit()

        sponsor = db.session.get(Sponsor, sponsor_ulid)
        issue = db.session.get(SponsorAdminIssue, issue.ulid)
        alert = db.session.execute(
            select(AdminAlert).where(
                AdminAlert.request_id == "req-sponsors-onboard-004",
                AdminAlert.target_ulid == sponsor_ulid,
                AdminAlert.reason_code == "advisory_sponsors_onboard",
            )
        ).scalar_one()

        assert receipt is not None
        assert sponsor is not None
        assert sponsor.readiness_status == "draft"
        assert sponsor.admin_review_required is True

        assert issue.source_status == "rejected"
        assert issue.closed_at_utc is not None

        assert alert.admin_status == "resolved"
        assert alert.source_status == "rejected"
        assert alert.close_reason == "rejected_in_sponsors"
        assert alert.closed_at_utc is not None
