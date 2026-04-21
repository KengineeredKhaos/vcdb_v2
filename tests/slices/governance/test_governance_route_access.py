# tests/slices/governance/test_governance_route_access.py

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
def governance_seeded(app):
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
        "/governance/policies",
        "/governance/canonicals",
        "/governance/roles",
    ],
)
def test_governance_routes_require_authentication(
    client,
    governance_seeded,
    path: str,
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
def test_governance_routes_deny_non_admin_users(
    client,
    governance_seeded,
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

    resp = client.get("/governance/policies", follow_redirects=False)
    assert_forbidden(resp)

    resp = client.get("/governance/canonicals", follow_redirects=False)
    assert_forbidden(resp)

    resp = client.get("/governance/roles", follow_redirects=False)
    assert_forbidden(resp)

    logout_if_possible(client)


def test_governance_routes_allow_admin(client, governance_seeded):
    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    resp = client.get("/governance/policies", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get("/governance/canonicals", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get("/governance/roles", follow_redirects=False)
    assert resp.status_code == 200
