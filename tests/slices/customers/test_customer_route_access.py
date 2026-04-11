# tests/slices/customers/test_customer_route_access.py

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.cli_seed import seed_bootstrap_impl
from app.extensions import db
from app.slices.auth import services as auth_svc
from app.slices.customers.models import Customer

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
def customer_seeded(app):
    """
    Seed real auth users plus a little customer/resource/sponsor data.
    Force real auth, then normalize bootstrap accounts back to known
    temporary-password state so tests remain deterministic.
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


def _first_customer_entity_ulid(app) -> str:
    with app.app_context():
        value = (
            db.session.execute(
                select(Customer.entity_ulid).order_by(Customer.entity_ulid)
            )
            .scalars()
            .first()
        )

    assert value, "Expected at least one seeded customer"
    return str(value)


def _assert_unauthenticated(resp) -> None:
    assert resp.status_code in {302, 303, 401}


def _assert_forbidden(resp) -> None:
    assert resp.status_code == 403


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


def test_customer_operator_routes_require_authentication(
    client,
    customer_seeded,
):
    entity_ulid = _first_customer_entity_ulid(customer_seeded)

    paths = [
        "/customers/",
        f"/customers/{entity_ulid}",
        f"/customers/{entity_ulid}/history",
        f"/customers/{entity_ulid}/referrals/new",
        f"/customers/{entity_ulid}/referrals/outcomes/new",
        f"/customers/intake/{entity_ulid}/eligibility",
        f"/customers/intake/{entity_ulid}/review",
    ]

    for path in paths:
        resp = client.get(path, follow_redirects=False)
        _assert_unauthenticated(resp)

    resp = client.post(
        f"/customers/intake/{entity_ulid}/eligibility",
        data={},
        follow_redirects=False,
    )
    _assert_unauthenticated(resp)


def test_customer_admin_inbox_requires_admin_for_anonymous(
    client,
    customer_seeded,
):
    resp = client.get("/customers/admin/inbox", follow_redirects=False)
    _assert_unauthenticated(resp)


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_customer_admin_inbox_denies_non_admin_users(
    client,
    customer_seeded,
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

    resp = client.get("/customers/admin/inbox", follow_redirects=False)
    _assert_forbidden(resp)

    _logout_if_possible(client)


@pytest.mark.xfail(
    reason="customers/admin_inbox.html not wired yet; route is UNTERMINATED"
)
def test_customer_admin_inbox_allows_admin(client, customer_seeded):
    _login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    resp = client.get("/customers/admin/inbox", follow_redirects=False)
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (ADMIN_USERNAME, ADMIN_TEMP_PASSWORD, ADMIN_SETTLED_PASSWORD),
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_customer_operator_surfaces_allow_authenticated_users(
    client,
    customer_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    entity_ulid = _first_customer_entity_ulid(customer_seeded)

    _login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    # Representative read surfaces
    resp = client.get("/customers/", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get(f"/customers/{entity_ulid}", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/{entity_ulid}/history",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/{entity_ulid}/referrals/new",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/{entity_ulid}/referrals/outcomes/new",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/intake/{entity_ulid}/eligibility",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Representative mutate surface:
    # stale/missing nonce should redirect within the customer flow,
    # but it should not fail as unauthenticated/forbidden.
    resp = client.post(
        f"/customers/intake/{entity_ulid}/eligibility",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}

    _logout_if_possible(client)
