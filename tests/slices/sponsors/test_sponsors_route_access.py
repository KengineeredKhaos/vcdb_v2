# tests/slices/sponsors/test_sponsors_route_access.py

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.slices.entity.models import EntityPerson
from app.slices.sponsors.models import Sponsor
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
    assert_unauthenticated,
    login_and_settle_password,
    logout_if_possible,
    seed_real_auth_world,
)


@pytest.fixture()
def sponsor_seeded(app):
    """
    Seed only the sponsor rows this file actually needs.
    """
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


def test_sponsor_routes_require_authentication(
    client,
    sponsor_seeded,
):
    sponsor_ulid = _first_sponsor_entity_ulid(sponsor_seeded)
    person_ulid = _first_person_entity_ulid(sponsor_seeded)

    paths = [
        "/sponsors",
        "/sponsors/search",
        f"/sponsors/{sponsor_ulid}",
        f"/sponsors/{sponsor_ulid}/detail",
        "/sponsors/onboard/start",
        f"/sponsors/onboard/start/{sponsor_ulid}",
        f"/sponsors/onboard/{sponsor_ulid}/profile",
        f"/sponsors/poc/attach/{person_ulid}",
        "/sponsors/funding-opportunities",
        "/sponsors/funding-intents/new",
    ]

    for path in paths:
        resp = client.get(path, follow_redirects=False)
        assert_unauthenticated(resp)

    resp = client.post("/sponsors", json={}, follow_redirects=False)
    assert_unauthenticated(resp)

    resp = client.post(
        f"/sponsors/{sponsor_ulid}/capabilities",
        json={},
        follow_redirects=False,
    )
    assert_unauthenticated(resp)


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (ADMIN_USERNAME, ADMIN_TEMP_PASSWORD, ADMIN_SETTLED_PASSWORD),
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_sponsor_operator_surfaces_allow_authenticated_users(
    client,
    sponsor_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    sponsor_ulid = _first_sponsor_entity_ulid(sponsor_seeded)
    person_ulid = _first_person_entity_ulid(sponsor_seeded)

    login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    # Representative JSON surfaces
    resp = client.get("/sponsors", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp = client.get(
        f"/sponsors/{sponsor_ulid}",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Representative HTML/operator surfaces
    resp = client.get("/sponsors/search", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get(
        f"/sponsors/{sponsor_ulid}/detail",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get("/sponsors/onboard/start", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get(
        f"/sponsors/onboard/start/{sponsor_ulid}",
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}

    resp = client.get(
        f"/sponsors/onboard/{sponsor_ulid}/profile",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/sponsors/poc/attach/{person_ulid}",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Funding routes
    resp = client.get(
        "/sponsors/funding-opportunities", follow_redirects=False
    )
    assert resp.status_code == 200

    resp = client.get("/sponsors/funding-intents/new", follow_redirects=False)
    assert resp.status_code == 200

    # Representative mutate surface:
    # after auth, missing entity_ulid should be validation failure,
    # not auth failure.
    resp = client.post("/sponsors", json={}, follow_redirects=False)
    assert resp.status_code == 400

    logout_if_possible(client)
