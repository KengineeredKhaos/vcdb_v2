# tests/slices/calendar/test_calendar_route_access.py

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
def calendar_seeded(app):
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
        "/calendar/hello",
        "/calendar/funding-demands",
    ],
)
def test_calendar_routes_require_authentication(
    client,
    calendar_seeded,
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
def test_calendar_hello_is_admin_only(
    client,
    calendar_seeded,
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

    resp = client.get("/calendar/hello", follow_redirects=False)
    assert_forbidden(resp)

    logout_if_possible(client)


def test_calendar_hello_allows_admin(client, calendar_seeded):
    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    resp = client.get("/calendar/hello", follow_redirects=False)
    assert resp.status_code == 200


def test_calendar_operator_list_surface_denies_auditor(
    client,
    calendar_seeded,
):
    login_and_settle_password(
        client,
        username=AUDITOR_USERNAME,
        temporary_password=AUDITOR_TEMP_PASSWORD,
        settled_password=AUDITOR_SETTLED_PASSWORD,
    )

    resp = client.get("/calendar/funding-demands", follow_redirects=False)
    assert_forbidden(resp)

    logout_if_possible(client)


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (ADMIN_USERNAME, ADMIN_TEMP_PASSWORD, ADMIN_SETTLED_PASSWORD),
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
    ],
)
def test_calendar_operator_list_surface_allows_staff_and_admin(
    client,
    calendar_seeded,
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

    resp = client.get("/calendar/funding-demands", follow_redirects=False)
    assert resp.status_code == 200

    logout_if_possible(client)
