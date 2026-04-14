# tests/slices/entity/test_entity_route_access.py

from __future__ import annotations

import pytest

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
def entity_seeded(app):
    """
    Seed only real auth users for route-access coverage.
    """
    seed_real_auth_world(
        app,
        customers=0,
        resources=0,
        sponsors=0,
        normalize_passwords=False,
    )
    return app


@pytest.mark.parametrize(
    "path",
    [
        "/entity/hello",
        "/entity/people",
        "/entity/orgs",
        "/entity/wizard/start",
        "/entity/wizard/person",
        "/entity/wizard/org",
    ],
)
def test_entity_routes_require_authentication(
    client, entity_seeded, path: str
):
    resp = client.get(path, follow_redirects=False)
    assert_unauthenticated(resp)


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_entity_hello_is_admin_only(
    client,
    entity_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    resp = client.get("/entity/hello", follow_redirects=False)
    assert_forbidden(resp)

    logout_if_possible(client)


def test_entity_hello_allows_admin(client, entity_seeded):
    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    resp = client.get("/entity/hello", follow_redirects=False)
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (ADMIN_USERNAME, ADMIN_TEMP_PASSWORD, ADMIN_SETTLED_PASSWORD),
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_entity_operator_surfaces_allow_authenticated_users(
    client,
    entity_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    # JSON list endpoints
    resp = client.get("/entity/people", follow_redirects=False)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True

    resp = client.get("/entity/orgs", follow_redirects=False)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True

    # Wizard entry surfaces
    resp = client.get("/entity/wizard/start", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get("/entity/wizard/person", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get("/entity/wizard/org", follow_redirects=False)
    assert resp.status_code == 200

    logout_if_possible(client)
