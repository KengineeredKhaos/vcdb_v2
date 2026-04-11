# tests/slices/auth/test_auth_route_access.py

from __future__ import annotations

import pytest

from app.cli_seed import seed_bootstrap_impl
from app.slices.auth import services as auth_svc

ADMIN_USERNAME = "admin.op"
ADMIN_TEMP_PASSWORD = "ChangeMe-AdminOp-1!"
ADMIN_SETTLED_PASSWORD = "AdminOp-TestPass-1!"

STAFF_USERNAME = "staff.op"
STAFF_TEMP_PASSWORD = "ChangeMe-StaffCiv-1!"
STAFF_SETTLED_PASSWORD = "StaffOp-TestPass-1!"

AUDITOR_USERNAME = "auditor.read"
AUDITOR_TEMP_PASSWORD = "ChangeMe-Auditor-1!"
AUDITOR_SETTLED_PASSWORD = "AuditorRead-TestPass-1!"


@pytest.fixture()
def auth_seeded(app):
    """
    Seed only what this file needs, and force real auth for access tests.

    Idempotent bootstrap is fine here; if the accounts already exist, the
    seed path should normalize them rather than explode.
    """
    with app.app_context():
        app.config["AUTH_MODE"] = "real"
        app.config["ALLOW_HEADER_AUTH"] = False
        app.config["AUTO_LOGIN_ADMIN"] = False

        seed_bootstrap_impl(
            fresh=False,
            force=False,
            faker_seed=1337,
            customers=0,
            resources=0,
            sponsors=0,
        )

    return app


def _user_view(app, username: str) -> dict[str, object]:
    with app.app_context():
        for row in auth_svc.list_user_views():
            if str(row.get("username", "")).strip().lower() == username:
                return row
    raise AssertionError(f"Missing seeded user: {username}")


def _assert_login_redirect(resp) -> None:
    assert resp.status_code in {302, 303}
    assert "/auth/login" in resp.headers.get("Location", "")


def _assert_unauthenticated(resp) -> None:
    assert resp.status_code in {302, 303, 401}


def _assert_forbidden(resp) -> None:
    assert resp.status_code == 403


def _try_login(client, *, username: str, password: str) -> bool:
    client.post(
        "/auth/login",
        data={
            "username": username,
            "password": password,
            "next": "/",
        },
        follow_redirects=False,
    )
    probe = client.get("/auth/change-password", follow_redirects=False)
    return probe.status_code == 200


def _login_and_settle_password(
    client,
    *,
    username: str,
    temporary_password: str,
    settled_password: str,
) -> None:
    """
    Handles both cases:
    - password was already rotated in a prior test
    - password is still temporary and must be changed now
    """
    if _try_login(client, username=username, password=settled_password):
        return

    ok = _try_login(client, username=username, password=temporary_password)
    assert ok, f"Could not log in as {username}"

    resp = client.post(
        "/auth/change-password",
        data={
            "current_password": temporary_password,
            "new_password": settled_password,
            "confirm_password": settled_password,
            "next": "/",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}


def _logout_if_possible(client) -> None:
    client.post("/auth/logout", follow_redirects=False)


def test_auth_public_and_self_service_access(client, auth_seeded):
    # Public login surface
    resp = client.get("/auth/login")
    assert resp.status_code == 200

    # Anonymous users should be bounced from self-service routes
    resp = client.get("/auth/change-password", follow_redirects=False)
    _assert_login_redirect(resp)

    resp = client.post("/auth/logout", follow_redirects=False)
    _assert_login_redirect(resp)


def test_auth_admin_routes_require_admin_for_anonymous(client, auth_seeded):
    target = _user_view(auth_seeded, STAFF_USERNAME)
    user_ulid = str(target["ulid"])

    resp = client.get("/auth/admin/users", follow_redirects=False)
    _assert_unauthenticated(resp)

    resp = client.get(
        f"/auth/admin/users/{user_ulid}", follow_redirects=False
    )
    _assert_unauthenticated(resp)

    resp = client.post(
        f"/auth/admin/users/{user_ulid}/roles",
        json={"roles": ["staff"]},
        follow_redirects=False,
    )
    _assert_unauthenticated(resp)


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
    _login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    target = _user_view(auth_seeded, STAFF_USERNAME)
    user_ulid = str(target["ulid"])

    # Self-service auth routes stay available
    resp = client.get("/auth/change-password", follow_redirects=False)
    assert resp.status_code == 200

    # Admin auth surface stays denied
    resp = client.get("/auth/admin/users", follow_redirects=False)
    _assert_forbidden(resp)

    resp = client.get(
        f"/auth/admin/users/{user_ulid}", follow_redirects=False
    )
    _assert_forbidden(resp)

    resp = client.post(
        f"/auth/admin/users/{user_ulid}/roles",
        json={"roles": ["staff"]},
        follow_redirects=False,
    )
    _assert_forbidden(resp)

    _logout_if_possible(client)


def test_auth_admin_routes_allow_admin(client, auth_seeded):
    _login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    target = _user_view(auth_seeded, STAFF_USERNAME)
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
