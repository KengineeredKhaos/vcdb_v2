# tests/slices/auth/test_auth_services.py

from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.slices.auth import services as svc
from app.slices.auth.models import Role, User


def _get_or_create_role(code: str) -> Role:
    role = db.session.query(Role).filter_by(code=code).one_or_none()
    if role is None:
        role = Role(code=code, is_active=True)
        db.session.add(role)
        db.session.flush()
    return role


def _make_user(
    *,
    username: str,
    password: str,
    roles: list[str],
    email: str | None = None,
    failed_login_attempts: int = 0,
) -> User:
    role_rows = [_get_or_create_role(code) for code in roles]
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        is_active=True,
        is_locked=False,
        must_change_password=False,
        failed_login_attempts=failed_login_attempts,
    )
    user.roles = role_rows
    db.session.add(user)
    db.session.flush()
    return user


def test_authenticate_success_resets_failed_attempts(app):
    with app.app_context():
        app.config["AUTH_MAX_FAILED_ATTEMPTS"] = 3
        username = "authsvc_alice"

        user = _make_user(
            username=username,
            password="correct-password",
            roles=["staff"],
            failed_login_attempts=2,
        )

        view = svc.authenticate(username, "correct-password")

        assert view["ulid"] == user.ulid
        assert view["username"] == username
        assert view["roles"] == ["staff"]
        assert view["failed_login_attempts"] == 0
        assert view["last_login_at_utc"] is not None


def test_authenticate_locks_after_max_failures(app):
    with app.app_context():
        app.config["AUTH_MAX_FAILED_ATTEMPTS"] = 3
        username = "authsvc_bob"

        user = _make_user(
            username=username,
            password="correct-password",
            roles=["staff"],
        )

        for _ in range(3):
            with pytest.raises(ValueError):
                svc.authenticate(username, "wrong-password")
        fresh = db.session.get(User, user.ulid)
        assert fresh is not None
        assert fresh.is_locked is True
        assert fresh.failed_login_attempts == 3
        assert fresh.locked_at_utc is not None


def test_set_account_roles_replaces_existing_roles(app):
    with app.app_context():
        _get_or_create_role("staff")
        _get_or_create_role("auditor")
        username = "authsvc_carol"

        user = _make_user(
            username=username,
            password="correct-password",
            roles=["staff"],
        )

        view = svc.set_account_roles(
            account_ulid=user.ulid,
            roles=["auditor"],
        )

        assert view["roles"] == ["auditor"]
        assert svc.get_user_roles(user.ulid) == ["auditor"]


def test_unlock_account_clears_lock_state(app):
    with app.app_context():
        username = "authsvc_dave"
        user = _make_user(
            username=username,
            password="correct-password",
            roles=["staff"],
        )
        user.is_locked = True
        user.failed_login_attempts = 5
        user.locked_at_utc = "2026-03-25T12:00:00+00:00"
        db.session.flush()

        view = svc.unlock_account(user.ulid)

        assert view["is_locked"] is False
        assert view["failed_login_attempts"] == 0
        assert view["locked_at_utc"] is None


def test_admin_reset_password_marks_change_required(app):
    with app.app_context():
        username = "authsvc_erin"
        user = _make_user(
            username=username,
            password="correct-password",
            roles=["staff"],
        )

        view = svc.admin_reset_password(
            account_ulid=user.ulid,
            temporary_password="temporary-pass",
        )

        assert view["must_change_password"] is True
        assert view["reset_issued_at_utc"] is not None


def test_change_own_password_clears_change_required(app):
    with app.app_context():
        username = "authsvc_frank"
        user = _make_user(
            username=username,
            password="old-password",
            roles=["staff"],
        )
        user.must_change_password = True
        db.session.flush()

        view = svc.change_own_password(
            user.ulid,
            current_password="old-password",
            new_password="new-password",
        )

        assert view["must_change_password"] is False
        assert view["password_changed_at_utc"] is not None


def test_set_account_active_toggles_state(app):
    with app.app_context():
        username = "authsvc_gina"
        user = _make_user(
            username=username,
            password="correct-password",
            roles=["staff"],
        )

        off_view = svc.set_account_active(user.ulid, is_active=False)
        on_view = svc.set_account_active(user.ulid, is_active=True)

        assert off_view["is_active"] is False
        assert on_view["is_active"] is True


def test_bootstrap_first_admin_is_closed_under_seeded_operator_mode(app):
    with app.app_context():
        with pytest.raises(
            PermissionError,
            match="First-admin bootstrap is closed",
        ):
            svc.bootstrap_first_admin(
                username="authsvc_bootstrap_admin",
                password="bootstrap-password",
            )


def test_list_user_views_returns_username_sorted_rows(app):
    with app.app_context():
        _make_user(
            username="authsvc_zulu",
            password="correct-password",
            roles=["staff"],
        )
        _make_user(
            username="authsvc_alpha",
            password="correct-password",
            roles=["auditor"],
        )

        rows = svc.list_user_views()
        usernames = [row["username"] for row in rows]

        assert "authsvc_alpha" in usernames
        assert "authsvc_zulu" in usernames
        assert usernames == sorted(usernames, key=str.lower)


def test_get_user_view_returns_expected_user(app):
    with app.app_context():
        username = "authsvc_harper"
        user = _make_user(
            username=username,
            password="correct-password",
            roles=["staff"],
        )

        view = svc.get_user_view(user.ulid)

        assert view["ulid"] == user.ulid
        assert view["username"] == username
        assert view["roles"] == ["staff"]
