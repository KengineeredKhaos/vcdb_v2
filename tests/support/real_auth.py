from __future__ import annotations

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


def configure_real_auth(app) -> None:
    app.config["AUTH_MODE"] = "real"
    app.config["ALLOW_HEADER_AUTH"] = False
    app.config["AUTO_LOGIN_ADMIN"] = False


def seed_real_auth_world(
    app,
    *,
    customers: int = 0,
    resources: int = 0,
    sponsors: int = 0,
    normalize_passwords: bool = True,
) -> None:
    with app.app_context():
        configure_real_auth(app)
        seed_bootstrap_impl(
            fresh=False,
            force=False,
            faker_seed=1337,
            customers=customers,
            resources=resources,
            sponsors=sponsors,
        )

    if normalize_passwords:
        reset_bootstrap_accounts(app)


def user_view(app, username: str) -> dict[str, object]:
    with app.app_context():
        for row in auth_svc.list_user_views():
            candidate = str(row.get("username", "")).strip().lower()
            if candidate == username:
                return row
    raise AssertionError(f"Missing seeded user: {username}")


def reset_bootstrap_account(
    app,
    *,
    username: str,
    temporary_password: str,
) -> None:
    with app.app_context():
        row = user_view(app, username)
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


def reset_bootstrap_accounts(app) -> None:
    reset_bootstrap_account(
        app,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
    )
    reset_bootstrap_account(
        app,
        username=STAFF_USERNAME,
        temporary_password=STAFF_TEMP_PASSWORD,
    )
    reset_bootstrap_account(
        app,
        username=AUDITOR_USERNAME,
        temporary_password=AUDITOR_TEMP_PASSWORD,
    )


def assert_login_redirect(resp) -> None:
    assert resp.status_code in {302, 303}
    assert "/auth/login" in resp.headers.get("Location", "")


def assert_unauthenticated(resp) -> None:
    assert resp.status_code in {302, 303, 401}


def assert_forbidden(resp) -> None:
    assert resp.status_code == 403


def try_login_via_auth_surface(
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


def login_and_settle_password(
    client,
    *,
    username: str,
    temporary_password: str,
    settled_password: str,
) -> None:
    if try_login_via_auth_surface(
        client,
        username=username,
        password=settled_password,
    ):
        return

    ok = try_login_via_auth_surface(
        client,
        username=username,
        password=temporary_password,
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


def logout_if_possible(client) -> None:
    client.post("/auth/logout", follow_redirects=False)
