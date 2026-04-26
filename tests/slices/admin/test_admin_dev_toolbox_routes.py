from __future__ import annotations

import pytest


@pytest.fixture
def anon_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


@pytest.fixture
def admin_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()
    client.environ_base.update({"HTTP_X_AUTH_STUB": "admin"})
    return client


@pytest.fixture
def staff_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()
    client.environ_base.update({"HTTP_X_AUTH_STUB": "staff"})
    return client


def test_public_index_renders(anon_client):
    resp = anon_client.get("/")
    assert resp.status_code == 200


def test_admin_dev_toolbox_renders_for_admin(admin_client):
    resp = admin_client.get("/admin/dev_toolbox/")
    assert resp.status_code == 200
    assert b"Development Toolbox" in resp.data


def test_admin_dev_toolbox_blocks_anonymous(anon_client):
    resp = anon_client.get("/admin/dev_toolbox/")
    assert resp.status_code in {302, 401, 403}


def test_admin_dev_toolbox_blocks_staff(staff_client):
    resp = staff_client.get("/admin/dev_toolbox/")
    assert resp.status_code in {302, 401, 403}
