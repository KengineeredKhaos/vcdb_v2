# tests/slices/sponsors/test_sponsors_route_access.py

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.cli_seed import seed_bootstrap_impl
from app.extensions import db
from app.slices.auth import services as auth_svc
from app.slices.entity.models import EntityPerson
from app.slices.sponsors.models import Sponsor

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
def sponsor_seeded(app):
    """
    Seed real auth users plus a little sponsor/resource/customer data.
    Force real auth, then normalize bootstrap accounts back to known
    temporary-password state so tests stay deterministic.
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

    _reset_bootstrap_account(
        app,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
    )
    _reset_bootstrap_account(
        app,
        username=STAFF_USERNAME,
        temporary_password=STAFF_TEMP_PASSWORD,
    )
    _reset_bootstrap_account(
        app,
        username=AUDITOR_USERNAME,
        temporary_password=AUDITOR_TEMP_PASSWORD,
    )

    return app


def _user_view(app, username: str) -> dict[str, object]:
    with app.app_context():
        for row in auth_svc.list_user_views():
            if str(row.get("username", "")).strip().lower() == username:
                return row
    raise AssertionError(f"Missing seeded user: {username}")


def _reset_bootstrap_account(
    app,
    *,
    username: str,
    temporary_password: str,
) -> None:
    with app.app_context():
        row = _user_view(app, username)
        account_ulid = str(row["ulid"])

        auth_svc.set_account_active(
            account_ulid=account_ulid,
            is_active=True,
        )
        auth_svc.unlock_account(account_ulid)
        auth_svc.admin_reset_password(
            account_ulid=account_ulid,
            temporary_password=temporary_password,
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


def _assert_unauthenticated(resp) -> None:
    assert resp.status_code in {302, 303, 401}


def _try_login_via_auth_surface(
    client,
    *,
    username: str,
    password: str,
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
        _assert_unauthenticated(resp)

    resp = client.post("/sponsors", json={}, follow_redirects=False)
    _assert_unauthenticated(resp)

    resp = client.post(
        f"/sponsors/{sponsor_ulid}/capabilities",
        json={},
        follow_redirects=False,
    )
    _assert_unauthenticated(resp)


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

    _login_and_settle_password(
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

    _logout_if_possible(client)
