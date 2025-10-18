# tests/auth/test_login_and_roles.py
import pytest


def test_login_page_renders(client):
    r = client.get("/auth/login")
    assert r.status_code == 200


def test_role_gate_requires_admin(client, app):
    # dev auto-login gives "admin" in debug; simulate non-admin by overriding session
    with client.session_transaction() as s:
        s["session_user"] = {
            "ulid": "01HXYZ...",
            "name": "test",
            "email": "t@e",
            "roles": ["user"],
        }
    r = client.post(
        "/auth/admin/users/does-not-matter/roles", json={"roles": ["user"]}
    )
    assert r.status_code in (401, 403)
