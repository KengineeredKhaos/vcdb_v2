# tests/slices/auth/test_auth_route_ledger.py

from __future__ import annotations

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.slices.auth import routes as auth_routes
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
) -> User:
    role_rows = [_get_or_create_role(code) for code in roles]
    user = User(
        username=username,
        email=None,
        password_hash=generate_password_hash(password),
        is_active=True,
        is_locked=False,
        must_change_password=False,
        failed_login_attempts=0,
    )
    user.roles = role_rows
    db.session.add(user)
    db.session.flush()
    return user


def test_login_failure_commits_failed_attempt_count_and_emits_event(
    app,
    monkeypatch,
):
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        auth_routes.event_bus,
        "emit",
        lambda **kwargs: events.append(kwargs),
    )

    with app.app_context():
        user = _make_user(
            username="authroute_alice",
            password="correct-password",
            roles=["staff"],
        )
        user_ulid = user.ulid
        db.session.commit()

    with app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={
                "ident": "authroute_alice",
                "password": "wrong-password",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302

    with app.app_context():
        fresh = db.session.get(User, user_ulid)
        assert fresh is not None
        assert fresh.failed_login_attempts == 1

    assert events
    assert events[0]["domain"] == "auth"
    assert events[0]["operation"] == "login_failed"
    assert events[0]["target_ulid"] == user_ulid


def test_login_success_emits_canonical_event(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        auth_routes.event_bus,
        "emit",
        lambda **kwargs: events.append(kwargs),
    )
    monkeypatch.setattr(
        auth_routes.svc,
        "authenticate",
        lambda ident, password: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAA",
            "username": "alice",
            "email": "",
            "roles": ["staff"],
            "must_change_password": False,
        },
    )

    with app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={
                "ident": "alice",
                "password": "correct-password",
                "next": "/logistics",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302

    assert events
    assert events[0]["domain"] == "auth"
    assert events[0]["operation"] == "login_succeeded"
    assert events[0]["target_ulid"] == "01ARZ3NDEKTSV4RRFFQ69G5FAA"


def test_logout_emits_canonical_event(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        auth_routes.event_bus,
        "emit",
        lambda **kwargs: events.append(kwargs),
    )
    monkeypatch.setattr(
        auth_routes.svc,
        "authenticate",
        lambda ident, password: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAB",
            "username": "alice",
            "email": "",
            "roles": ["staff"],
            "must_change_password": False,
        },
    )

    with app.test_client() as client:
        client.post(
            "/auth/login",
            data={"ident": "alice", "password": "correct-password"},
            follow_redirects=False,
        )
        events.clear()

        resp = client.post("/auth/logout", follow_redirects=False)

        assert resp.status_code == 302

    assert events
    assert events[0]["domain"] == "auth"
    assert events[0]["operation"] == "logout_succeeded"


def test_admin_create_user_emits_canonical_event(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        auth_routes.event_bus,
        "emit",
        lambda **kwargs: events.append(kwargs),
    )
    monkeypatch.setattr(
        auth_routes.svc,
        "create_account",
        lambda **kwargs: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAC",
            "username": kwargs["username"],
            "email": kwargs.get("email") or "",
            "roles": kwargs["roles"],
            "is_active": kwargs["is_active"],
            "must_change_password": kwargs["must_change_password"],
        },
    )

    with app.test_client() as client:
        resp = client.post(
            "/auth/admin/users",
            json={
                "username": "new-user",
                "password": "temporary-pass",
                "roles": ["staff"],
                "is_active": True,
                "must_change_password": True,
            },
            headers={"X-Auth-Stub": "admin"},
        )

        assert resp.status_code == 201

    assert events
    assert events[0]["domain"] == "auth"
    assert events[0]["operation"] == "account_created"
    assert events[0]["target_ulid"] == "01ARZ3NDEKTSV4RRFFQ69G5FAC"
