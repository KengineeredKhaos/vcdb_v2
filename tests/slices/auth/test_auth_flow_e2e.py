# tests/slices/auth/test_auth_flow_e2e.py

from __future__ import annotations

from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.slices.auth import routes as auth_routes
from app.slices.auth.models import Role, User




def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


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
    must_change_password: bool,
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



def test_first_login_password_change_flow_works_end_to_end(
    app,
    monkeypatch,
):
    app.config["WTF_CSRF_ENABLED"] = False
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        auth_routes.event_bus,
        "emit",
        lambda **kwargs: events.append(kwargs),
    )

    with app.app_context():
        username = _unique_username("flow_user")
        user = _make_user(
            username=username,
            password="temporary-pass",
            roles=["staff"],
            must_change_password=True,
        )
        user_ulid = user.ulid
        db.session.commit()

    with app.test_client() as client:
        login_resp = client.post(
            "/auth/login",
            data={
                "username": username,
                "password": "temporary-pass",
                "next": "/logistics",
            },
            follow_redirects=False,
        )

        assert login_resp.status_code == 302
        assert "/auth/change-password" in login_resp.headers["Location"]

        with client.session_transaction() as sess:
            ident = sess.get("session_user")
            assert ident is not None
            assert ident["ulid"] == user_ulid
            assert ident["must_change_password"] is True

        change_resp = client.post(
            "/auth/change-password",
            data={
                "current_password": "temporary-pass",
                "new_password": "new-password",
                "confirm_password": "new-password",
                "next": "/logistics",
            },
            follow_redirects=False,
        )

        assert change_resp.status_code == 302
        assert change_resp.headers["Location"].endswith("/logistics")

        with client.session_transaction() as sess:
            ident = sess.get("session_user")
            assert ident is not None
            assert ident["ulid"] == user_ulid
            assert ident["must_change_password"] is False

        logout_resp = client.post("/auth/logout", follow_redirects=False)
        assert logout_resp.status_code == 302

        old_login_resp = client.post(
            "/auth/login",
            data={
                "username": username,
                "password": "temporary-pass",
            },
            follow_redirects=False,
        )
        assert old_login_resp.status_code == 302
        assert "/auth/login" in old_login_resp.headers["Location"]

        new_login_resp = client.post(
            "/auth/login",
            data={
                "username": username,
                "password": "new-password",
                "next": "/logistics",
            },
            follow_redirects=False,
        )
        assert new_login_resp.status_code == 302
        assert new_login_resp.headers["Location"].endswith("/logistics")

    with app.app_context():
        fresh = db.session.get(User, user_ulid)
        assert fresh is not None
        assert fresh.must_change_password is False
        assert fresh.password_changed_at_utc is not None
        assert fresh.failed_login_attempts == 0

    operations = [event["operation"] for event in events]
    assert operations == [
        "login_succeeded",
        "password_changed",
        "logout_succeeded",
        "login_failed",
        "login_succeeded",
    ]

    password_changed_event = events[1]
    assert password_changed_event["actor_ulid"] == user_ulid
    assert password_changed_event["target_ulid"] == user_ulid

    final_login_event = events[-1]
    assert final_login_event["meta"]["must_change_password"] is False
