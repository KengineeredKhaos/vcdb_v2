# tests/slices/auth/test_auth_route_access.py

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
    assert_login_redirect,
    assert_unauthenticated,
    login_and_settle_password,
    logout_if_possible,
    seed_real_auth_world,
    user_view,
)


@pytest.fixture()
def auth_seeded(app):
    """
    Seed only what this file needs and force real auth.
    """
    seed_real_auth_world(
        app,
        customers=0,
        resources=0,
        sponsors=0,
        normalize_passwords=False,
    )
    return app


def test_auth_public_and_self_service_access(client, auth_seeded):
    # Public login surface
    resp = client.get("/auth/login")
    assert resp.status_code == 200

    # Anonymous users should be bounced from self-service routes
    resp = client.get("/auth/change-password", follow_redirects=False)
    assert_login_redirect(resp)

    resp = client.post("/auth/logout", follow_redirects=False)
    assert_login_redirect(resp)


def test_auth_admin_routes_require_admin_for_anonymous(client, auth_seeded):
    target = user_view(auth_seeded, STAFF_USERNAME)
    user_ulid = str(target["ulid"])

    resp = client.get("/auth/admin/users", follow_redirects=False)
    assert_unauthenticated(resp)

    resp = client.get(
        f"/auth/admin/users/{user_ulid}", follow_redirects=False
    )
    assert_unauthenticated(resp)

    resp = client.post(
        f"/auth/admin/users/{user_ulid}/roles",
        json={"roles": ["staff"]},
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
def test_auth_admin_routes_deny_non_admin_users(
    client,
    auth_seeded,
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

    target = user_view(auth_seeded, STAFF_USERNAME)
    user_ulid = str(target["ulid"])

    # Self-service auth routes stay available
    resp = client.get("/auth/change-password", follow_redirects=False)
    assert resp.status_code == 200

    # Admin auth surface stays denied
    resp = client.get("/auth/admin/users", follow_redirects=False)
    assert_forbidden(resp)

    resp = client.get(
        f"/auth/admin/users/{user_ulid}", follow_redirects=False
    )
    assert_forbidden(resp)

    resp = client.post(
        f"/auth/admin/users/{user_ulid}/roles",
        json={"roles": ["staff"]},
        follow_redirects=False,
    )
    assert_forbidden(resp)

    logout_if_possible(client)


def test_auth_admin_routes_allow_admin(client, auth_seeded):
    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    target = user_view(auth_seeded, STAFF_USERNAME)
    user_ulid = str(target["ulid"])
    is_active = bool(target.get("is_active", True))

    resp = client.get("/auth/admin/users", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get(
        f"/auth/admin/users/{user_ulid}", follow_redirects=False
    )
    assert resp.status_code == 200

    # Representative admin mutation: re-apply the same role set
    resp = client.post(
        f"/auth/admin/users/{user_ulid}/roles",
        json={"roles": ["staff"]},
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Representative admin mutation: idempotent active toggle
    resp = client.post(
        f"/auth/admin/users/{user_ulid}/active",
        json={"is_active": is_active},
        follow_redirects=False,
    )
    assert resp.status_code == 200
