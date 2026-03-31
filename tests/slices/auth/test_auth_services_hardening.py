# tests/slices/auth/test_auth_services_hardening.py

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
    must_change_password: bool = False,
) -> User:
    role_rows = [_get_or_create_role(code) for code in roles]
    user = User(
        username=username,
        email=None,
        password_hash=generate_password_hash(password),
        is_active=True,
        is_locked=False,
        must_change_password=must_change_password,
        failed_login_attempts=0,
    )
    user.roles = role_rows
    db.session.add(user)
    db.session.flush()
    return user



def test_authenticate_username_lookup_is_case_insensitive(app):
    with app.app_context():
        user = _make_user(
            username="MixedCaseUser",
            password="correct-password",
            roles=["staff"],
        )

        view = svc.authenticate("mixedcaseuser", "correct-password")

        assert view["ulid"] == user.ulid
        assert view["username"] == "MixedCaseUser"



def test_change_own_password_rejects_wrong_current_password(app):
    with app.app_context():
        user = _make_user(
            username="authsvc_wrong_current",
            password="old-password",
            roles=["staff"],
            must_change_password=True,
        )

        with pytest.raises(ValueError, match="Current password is incorrect"):
            svc.change_own_password(
                user.ulid,
                current_password="not-the-current-password",
                new_password="new-password",
            )



def test_change_own_password_invalidates_old_password(app):
    with app.app_context():
        user = _make_user(
            username="authsvc_rotate_me",
            password="old-password",
            roles=["staff"],
            must_change_password=True,
        )

        svc.change_own_password(
            user.ulid,
            current_password="old-password",
            new_password="new-password",
        )

        with pytest.raises(ValueError, match="Invalid username or password"):
            svc.authenticate(user.username, "old-password")

        fresh = svc.authenticate(user.username, "new-password")

        assert fresh["ulid"] == user.ulid
        assert fresh["must_change_password"] is False
