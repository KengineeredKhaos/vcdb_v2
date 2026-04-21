# /tests/slices/web/test_entry_page_smoke.py

from __future__ import annotations

import pytest

from tests.support.real_auth import (
    ADMIN_SETTLED_PASSWORD,
    ADMIN_TEMP_PASSWORD,
    ADMIN_USERNAME,
    STAFF_SETTLED_PASSWORD,
    STAFF_TEMP_PASSWORD,
    STAFF_USERNAME,
    login_and_settle_password,
    seed_real_auth_world,
)


@pytest.fixture()
def entry_seeded(app):
    seed_real_auth_world(
        app,
        customers=1,
        resources=1,
        sponsors=1,
        normalize_passwords=False,
    )
    return app


def test_homepage_renders_for_anonymous(client, entry_seeded):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "VCDB operator portal" in text
    assert "Log in" in text


def test_homepage_renders_staff_workbench(client, entry_seeded):
    login_and_settle_password(
        client,
        username=STAFF_USERNAME,
        temporary_password=STAFF_TEMP_PASSWORD,
        settled_password=STAFF_SETTLED_PASSWORD,
    )

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Operator workbench" in text
    assert "Find / Open Customer" in text
    assert "Search / Open Resources" in text
    assert "Search / Open Sponsors" in text
    assert "Admin Dashboard" not in text


def test_homepage_renders_admin_entry_links(client, entry_seeded):
    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Operator workbench" in text
    assert "Admin Dashboard" in text


def test_login_page_smoke(client, entry_seeded):
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 200
