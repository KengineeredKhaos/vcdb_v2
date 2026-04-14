# tests/slices/resources/test_resources_route_access.py

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.slices.entity.models import EntityPerson
from app.slices.resources.models import Resource
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


@pytest.fixture()
def resource_seeded(app):
    """
    Seed only the resource rows this file actually needs.
    """
    seed_real_auth_world(
        app,
        customers=0,
        resources=1,
        sponsors=0,
        normalize_passwords=False,
    )
    return app


def _first_resource_entity_ulid(app) -> str:
    with app.app_context():
        value = (
            db.session.execute(
                select(Resource.entity_ulid).order_by(Resource.entity_ulid)
            )
            .scalars()
            .first()
        )

    assert value, "Expected at least one seeded resource"
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


def test_resources_operator_routes_require_authentication(
    client,
    resource_seeded,
):
    resource_ulid = _first_resource_entity_ulid(resource_seeded)
    person_ulid = _first_person_entity_ulid(resource_seeded)

    paths = [
        "/resources/",
        "/resources/search?format=json",
        f"/resources/{resource_ulid}?format=json",
        f"/resources/{resource_ulid}/profile-hints?format=json",
        f"/resources/{resource_ulid}/pocs-expanded",
        "/resources/onboard/start",
        f"/resources/onboard/{resource_ulid}/profile",
        f"/resources/poc/attach/{person_ulid}",
    ]

    for path in paths:
        resp = client.get(path, follow_redirects=False)
        assert_unauthenticated(resp)

    resp = client.post("/resources/ensure", json={}, follow_redirects=False)
    assert_unauthenticated(resp)


def test_resources_admin_review_requires_admin_for_anonymous(
    client,
    resource_seeded,
):
    fake_ulid = "01H00000000000000000000000"

    resp = client.post(
        f"/resources/admin-review/{fake_ulid}/approve",
        follow_redirects=False,
    )
    assert_unauthenticated(resp)

    resp = client.post(
        f"/resources/admin-review/{fake_ulid}/reject",
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
def test_resources_admin_review_denies_non_admin_users(
    client,
    resource_seeded,
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

    resp = client.post(
        f"/resources/admin-review/{fake_ulid}/approve",
        follow_redirects=False,
    )
    assert_forbidden(resp)

    resp = client.post(
        f"/resources/admin-review/{fake_ulid}/reject",
        follow_redirects=False,
    )
    assert_forbidden(resp)

    logout_if_possible(client)


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (ADMIN_USERNAME, ADMIN_TEMP_PASSWORD, ADMIN_SETTLED_PASSWORD),
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_resources_operator_surfaces_allow_authenticated_users(
    client,
    resource_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    resource_ulid = _first_resource_entity_ulid(resource_seeded)
    person_ulid = _first_person_entity_ulid(resource_seeded)

    login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    # Representative read surfaces
    resp = client.get("/resources/search?format=json", follow_redirects=False)

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp = client.get(
        f"/resources/{resource_ulid}?format=json",
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp = client.get(
        f"/resources/{resource_ulid}/profile-hints?format=json",
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp = client.get(
        f"/resources/{resource_ulid}/pocs-expanded",
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp = client.get("/resources/onboard/start", follow_redirects=False)

    assert resp.status_code == 200

    resp = client.get(
        f"/resources/onboard/{resource_ulid}/profile",
        follow_redirects=False,
    )

    assert resp.status_code == 200

    resp = client.get(
        f"/resources/poc/attach/{person_ulid}",
        follow_redirects=False,
    )

    assert resp.status_code == 200

    # Representative mutate surface:
    # after auth, missing entity_ulid should be a validation failure,
    # not an auth failure.
    resp = client.post("/resources/ensure", json={}, follow_redirects=False)

    assert resp.status_code == 400

    logout_if_possible(client)
