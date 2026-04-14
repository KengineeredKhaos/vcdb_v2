# tests/slices/auth/test_auth_routes.py

from __future__ import annotations

from app.slices.auth import routes as auth_routes


def test_login_post_stores_session_identity(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False

    monkeypatch.setattr(
        auth_routes.svc,
        "authenticate",
        lambda username, password: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
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
                "username": "alice",
                "password": "correct-password",
                "next": "/logistics",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/logistics")

        with client.session_transaction() as sess:
            ident = sess.get("session_user")
            assert ident is not None
            assert ident["ulid"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
            assert ident["username"] == "alice"
            assert ident["roles"] == ["staff"]


def test_login_post_redirects_to_change_password_when_flagged(
    app,
    monkeypatch,
):
    app.config["WTF_CSRF_ENABLED"] = False

    monkeypatch.setattr(
        auth_routes.svc,
        "authenticate",
        lambda username, password: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAA",
            "username": "reset-user",
            "email": "",
            "roles": ["staff"],
            "must_change_password": True,
        },
    )

    with app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={
                "username": "reset-user",
                "password": "temporary-pass",
                "next": "/logistics",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert "/auth/change-password" in resp.headers["Location"]


def test_change_password_post_clears_session_flag(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False

    monkeypatch.setattr(
        auth_routes.svc,
        "authenticate",
        lambda username, password: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAB",
            "username": "reset-user",
            "email": "",
            "roles": ["staff"],
            "must_change_password": True,
        },
    )
    monkeypatch.setattr(
        auth_routes.svc,
        "change_own_password",
        lambda account_ulid, current_password, new_password: {
            "ulid": account_ulid,
            "username": "reset-user",
            "email": "",
            "roles": ["staff"],
            "must_change_password": False,
        },
    )

    with app.test_client() as client:
        client.post(
            "/auth/login",
            data={"username": "reset-user", "password": "temporary-pass"},
            follow_redirects=False,
        )

        resp = client.post(
            "/auth/change-password",
            data={
                "current_password": "temporary-pass",
                "new_password": "new-password",
                "confirm_password": "new-password",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302

        with client.session_transaction() as sess:
            ident = sess.get("session_user")
            assert ident is not None
            assert ident["must_change_password"] is False


def test_change_password_post_rejects_confirmation_mismatch(
    app,
    monkeypatch,
):
    app.config["WTF_CSRF_ENABLED"] = False

    monkeypatch.setattr(
        auth_routes.svc,
        "authenticate",
        lambda username, password: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAC",
            "username": "reset-user",
            "email": "",
            "roles": ["staff"],
            "must_change_password": True,
        },
    )

    called = {"count": 0}

    def _should_not_run(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("change_own_password should not be called")

    monkeypatch.setattr(
        auth_routes.svc,
        "change_own_password",
        _should_not_run,
    )

    with app.test_client() as client:
        client.post(
            "/auth/login",
            data={"username": "reset-user", "password": "temporary-pass"},
            follow_redirects=False,
        )

        resp = client.post(
            "/auth/change-password",
            data={
                "current_password": "temporary-pass",
                "new_password": "new-password",
                "confirm_password": "not-the-same",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert "/auth/change-password" in resp.headers["Location"]

        with client.session_transaction() as sess:
            ident = sess.get("session_user")
            assert ident is not None
            assert ident["must_change_password"] is True

    assert called["count"] == 0


def test_logout_clears_session_identity(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False

    monkeypatch.setattr(
        auth_routes.svc,
        "authenticate",
        lambda username, password: {
            "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "username": "alice",
            "email": "",
            "roles": ["staff"],
            "must_change_password": False,
        },
    )

    with app.test_client() as client:
        client.post(
            "/auth/login",
            data={"username": "alice", "password": "correct-password"},
            follow_redirects=False,
        )

        resp = client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            assert "session_user" not in sess


def test_admin_set_roles_returns_400_on_bad_roles_payload(
    app,
    monkeypatch,
):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    monkeypatch.setattr(
        auth_routes.svc,
        "set_account_roles",
        lambda account_ulid, roles: {
            "ulid": account_ulid,
            "username": "alice",
            "email": "",
            "roles": roles,
        },
    )

    with app.test_client() as client:
        resp = client.post(
            "/auth/admin/users/01ARZ3NDEKTSV4RRFFQ69G5FAV/roles",
            json={"roles": "admin"},
            headers={"X-Auth-Stub": "admin"},
        )

        assert resp.status_code == 400


def test_admin_set_roles_happy_path(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    monkeypatch.setattr(
        auth_routes.svc,
        "set_account_roles",
        lambda account_ulid, roles: {
            "ulid": account_ulid,
            "username": "alice",
            "email": "",
            "roles": roles,
            "is_active": True,
            "is_locked": False,
            "must_change_password": False,
        },
    )

    with app.test_client() as client:
        resp = client.post(
            "/auth/admin/users/01ARZ3NDEKTSV4RRFFQ69G5FAV/roles",
            json={"roles": ["auditor"]},
            headers={"X-Auth-Stub": "admin"},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["roles"] == ["auditor"]


def test_admin_create_user_happy_path(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

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
        payload = resp.get_json()
        assert payload["username"] == "new-user"
        assert payload["roles"] == ["staff"]


def test_admin_reset_unlock_and_set_active_routes(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    monkeypatch.setattr(
        auth_routes.svc,
        "admin_reset_password",
        lambda account_ulid, temporary_password: {
            "ulid": account_ulid,
            "username": "alice",
            "email": "",
            "roles": ["staff"],
            "is_active": True,
            "is_locked": True,
            "must_change_password": True,
        },
    )
    monkeypatch.setattr(
        auth_routes.svc,
        "unlock_account",
        lambda account_ulid: {
            "ulid": account_ulid,
            "username": "alice",
            "email": "",
            "roles": ["staff"],
            "is_active": True,
            "is_locked": False,
            "must_change_password": True,
        },
    )
    monkeypatch.setattr(
        auth_routes.svc,
        "set_account_active",
        lambda account_ulid, is_active: {
            "ulid": account_ulid,
            "username": "alice",
            "email": "",
            "roles": ["staff"],
            "is_active": is_active,
            "is_locked": False,
            "must_change_password": False,
        },
    )

    with app.test_client() as client:
        reset_resp = client.post(
            "/auth/admin/users/01ARZ3NDEKTSV4RRFFQ69G5FAD/reset-password",
            json={"temporary_password": "temp-pass"},
            headers={"X-Auth-Stub": "admin"},
        )
        unlock_resp = client.post(
            "/auth/admin/users/01ARZ3NDEKTSV4RRFFQ69G5FAD/unlock",
            headers={"X-Auth-Stub": "admin"},
        )
        active_resp = client.post(
            "/auth/admin/users/01ARZ3NDEKTSV4RRFFQ69G5FAD/active",
            json={"is_active": False},
            headers={"X-Auth-Stub": "admin"},
        )

        assert reset_resp.status_code == 200
        assert unlock_resp.status_code == 200
        assert active_resp.status_code == 200
        assert active_resp.get_json()["is_active"] is False


def test_first_admin_bootstrap_route_is_not_registered(app):
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        resp = client.post(
            "/auth/bootstrap/first-admin",
            json={
                "username": "bootstrap-admin",
                "password": "bootstrap-password",
            },
        )

    assert resp.status_code == 404


def test_admin_list_users_happy_path(app, monkeypatch):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    monkeypatch.setattr(
        auth_routes.svc,
        "list_user_views",
        lambda: [
            {
                "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAF",
                "username": "alpha",
                "email": "",
                "roles": ["staff"],
            },
            {
                "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAG",
                "username": "zulu",
                "email": "",
                "roles": ["auditor"],
            },
        ],
    )

    with app.test_client() as client:
        resp = client.get(
            "/auth/admin/users",
            headers={"X-Auth-Stub": "admin"},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["count"] == 2
        assert len(payload["items"]) == 2


def test_admin_get_user_happy_path(app, monkeypatch):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    monkeypatch.setattr(
        auth_routes.svc,
        "get_user_view",
        lambda account_ulid: {
            "ulid": account_ulid,
            "username": "alpha",
            "email": "",
            "roles": ["staff"],
            "is_active": True,
            "is_locked": False,
            "must_change_password": False,
        },
    )

    with app.test_client() as client:
        resp = client.get(
            "/auth/admin/users/01ARZ3NDEKTSV4RRFFQ69G5FAH",
            headers={"X-Auth-Stub": "admin"},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["username"] == "alpha"
