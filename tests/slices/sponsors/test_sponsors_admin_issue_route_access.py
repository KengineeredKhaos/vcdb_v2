# tests/slices/sponsors/test_sponsors_admin_issue_route_access.py

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.slices.entity.models import EntityPerson
from app.slices.sponsors import admin_issue_services as issue_svc
from app.slices.sponsors.models import Sponsor, SponsorAdminIssue
from tests.support.real_auth import (
    ADMIN_SETTLED_PASSWORD,
    ADMIN_TEMP_PASSWORD,
    ADMIN_USERNAME,
    AUDITOR_SETTLED_PASSWORD,
    AUDITOR_TEMP_PASSWORD,
    AUDITOR_USERNAME,
    STAFF_SETTLED_PASSWORD,
    STAFF_TEMP_PASSWORD,
    STAFF_USERNAME,
    assert_forbidden,
    assert_unauthenticated,
    login_and_settle_password,
    logout_if_possible,
    seed_real_auth_world,
)


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


def test_sponsors_admin_issue_requires_admin_for_anonymous(
    client,
    sponsor_seeded,
):
    fake_ulid = "01H00000000000000000000000"

    resp = client.get(
        f"/sponsors/admin-issue/{fake_ulid}",
        follow_redirects=False,
    )
    assert_unauthenticated(resp)

    resp = client.post(
        f"/sponsors/admin-issue/{fake_ulid}/approve",
        follow_redirects=False,
    )
    assert_unauthenticated(resp)

    resp = client.post(
        f"/sponsors/admin-issue/{fake_ulid}/reject",
        follow_redirects=False,
    )
    assert_unauthenticated(resp)


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_sponsors_admin_issue_denies_non_admin_users(
    client,
    sponsor_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    fake_ulid = "01H00000000000000000000000"

    login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    resp = client.get(
        f"/sponsors/admin-issue/{fake_ulid}",
        follow_redirects=False,
    )
    assert_forbidden(resp)

    resp = client.post(
        f"/sponsors/admin-issue/{fake_ulid}/approve",
        follow_redirects=False,
    )
    assert_forbidden(resp)

    resp = client.post(
        f"/sponsors/admin-issue/{fake_ulid}/reject",
        follow_redirects=False,
    )
    assert_forbidden(resp)

    logout_if_possible(client)


def test_sponsors_admin_issue_allows_admin_route_surface(
    client,
    sponsor_seeded,
):
    sponsor_ulid = _first_sponsor_entity_ulid(sponsor_seeded)
    actor_ulid = _first_person_entity_ulid(sponsor_seeded)

    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    with sponsor_seeded.app_context():
        issue_svc.raise_onboard_admin_issue(
            entity_ulid=sponsor_ulid,
            request_id="req-sponsors-route-access-001",
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        issue = db.session.execute(
            select(SponsorAdminIssue).where(
                SponsorAdminIssue.request_id
                == "req-sponsors-route-access-001"
            )
        ).scalar_one()

    resp = client.get(
        f"/sponsors/admin-issue/{issue.ulid}",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    logout_if_possible(client)
