# tests/slices/entity/test_entity_route_access.py

from __future__ import annotations

import pytest

from app.cli_seed import seed_bootstrap_impl


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
def entity_seeded(app):
    """
    Seed real auth users plus a little domain data.
    Force real auth so these tests prove the real login path.
    """
    with app.app_context():
        app.config["AUTH_MODE"] = "real"
        app.config["ALLOW_HEADER_AUTH"] = False
        app.config["AUTO_LOGIN_ADMIN"] = False

        seed_bootstrap_impl(
            fresh=False,
            force=False,
            faker_seed=1337,
            customers=2,
            resources=1,
            sponsors=1,
        )

    return app


def _assert_unauthenticated(resp) -> None:
    assert resp.status_code in {302, 303, 401}


def _assert_forbidden(resp) -> None:
    assert resp.status_code == 403


def _try_login_via_auth_surface(
    client, *, username: str, password: str
) -> bool:
    resp = client.post(
        "/auth/login",
        data={
            "username": username,
            "password": password,
            "next": "/",
        },
        follow_redirects=False,
    )

    if resp.status_code not in {302, 303}:
        return False

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
    Works whether the password was already rotated or is still temporary.
    """
    if _try_login_via_auth_surface(
        client, username=username, password=settled_password
    ):
        return

    ok = _try_login_via_auth_surface(
        client, username=username, password=temporary_password
    )
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
    _assert_unauthenticated(resp)


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
    _login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    resp = client.get("/entity/hello", follow_redirects=False)
    _assert_forbidden(resp)

    _logout_if_possible(client)


def test_entity_hello_allows_admin(client, entity_seeded):
    _login_and_settle_password(
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
    _login_and_settle_password(
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

    _logout_if_possible(client)
