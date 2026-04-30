# tests/slices/admin/test_admin_routes.py

from __future__ import annotations

import pytest


@pytest.fixture
def admin_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    client = app.test_client()
    client.environ_base.update({"HTTP_X_AUTH_STUB": "admin"})
    return client


def test_admin_index_renders(admin_client):
    resp = admin_client.get("/admin/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Ledger" in body
    assert "Open Ledger Control Surface" in body
    assert "Backup gate:" in body


def test_admin_inbox_renders(admin_client):
    resp = admin_client.get("/admin/inbox/")
    assert resp.status_code == 200


def test_admin_cron_renders(admin_client):
    resp = admin_client.get("/admin/cron/")
    assert resp.status_code == 200


def test_admin_policy_index_renders(admin_client):
    resp = admin_client.get("/admin/policy/")
    assert resp.status_code == 200


def test_admin_auth_operators_renders(admin_client):
    resp = admin_client.get("/admin/auth/operators/")
    assert resp.status_code == 200


def test_admin_pages_require_admin_role(client, app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True

    client.environ_base.update({"HTTP_X_AUTH_STUB": "staff"})

    assert client.get("/admin/").status_code in {302, 403}
    assert client.get("/admin/inbox/").status_code in {302, 403}
    assert client.get("/admin/cron/").status_code in {302, 403}
    assert client.get("/admin/policy/").status_code in {302, 403}
    assert client.get("/admin/auth/operators/").status_code in {302, 403}
