from __future__ import annotations

import pytest

from app.slices.admin import operator_onboard_routes as routes
from app.slices.admin import operator_onboard_services as svc


@pytest.fixture
def admin_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()
    client.environ_base.update({"HTTP_X_AUTH_STUB": "admin"})
    return client


def test_operator_onboard_get_renders(admin_client):
    resp = admin_client.get("/admin/auth/operators/onboard/")
    assert resp.status_code == 200


def test_operator_onboard_review_renders(admin_client):
    resp = admin_client.post(
        "/admin/auth/operators/onboard/review",
        data={
            "first_name": "Michael",
            "last_name": "Shaw",
            "preferred_name": "Mike",
            "username": "mshaw",
            "email": "mshaw@example.test",
            "temporary_password": "temp-pass-1",
            "role_code": "staff",
        },
    )

    assert resp.status_code == 200
    assert b"Mike Shaw" in resp.data


def test_operator_onboard_commit_redirects_on_success(
    admin_client,
    monkeypatch,
):
    monkeypatch.setattr(routes.db.session, "commit", lambda: None)

    monkeypatch.setattr(
        svc,
        "commit_operator_onboard",
        lambda **kwargs: svc.OperatorOnboardResultDTO(
            entity_ulid="01AAAAAAAAAAAAAAAAAAAAAAAA",
            account_ulid="01BBBBBBBBBBBBBBBBBBBBBBBB",
            username="mshaw",
            role_code="staff",
            display_name="Mike Shaw",
            email="mshaw@example.test",
        ),
    )

    admin_client.post(
        "/admin/auth/operators/onboard/review",
        data={
            "first_name": "Michael",
            "last_name": "Shaw",
            "preferred_name": "Mike",
            "username": "mshaw",
            "email": "mshaw@example.test",
            "temporary_password": "temp-pass-1",
            "role_code": "staff",
        },
    )

    with admin_client.session_transaction() as sess:
        token = sess[routes._PREVIEW_SESSION_KEY]["token"]

    resp = admin_client.post(
        "/admin/auth/operators/onboard/commit",
        data={"preview_token": token},
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/auth/operators/")


def test_rbac_role_get_renders(admin_client, monkeypatch):
    monkeypatch.setattr(
        svc,
        "build_rbac_maintenance_page",
        lambda **kwargs: svc.OperatorRbacMaintenancePageDTO(
            title="Operator RBAC Maintenance",
            summary="summary",
            account_ulid="01BBBBBBBBBBBBBBBBBBBBBBBB",
            entity_ulid="01AAAAAAAAAAAAAAAAAAAAAAAA",
            username="mshaw",
            email="mshaw@example.test",
            display_name="Mike Shaw",
            current_role_code="staff",
            current_role_label="Staff (standard CRUD)",
        ),
    )

    resp = admin_client.get(
        "/admin/auth/operators/01BBBBBBBBBBBBBBBBBBBBBBBB/rbac-role"
    )
    assert resp.status_code == 200
    assert b"Mike Shaw" in resp.data
