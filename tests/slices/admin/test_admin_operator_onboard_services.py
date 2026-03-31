from __future__ import annotations

import pytest

from app.slices.admin import operator_onboard_services as svc


def test_build_operator_onboard_review_uses_preferred_name():
    review = svc.build_operator_onboard_review(
        first_name="Michael",
        last_name="Shaw",
        preferred_name="Mike",
        username="mshaw",
        email="mshaw@example.test",
        temporary_password="temp-pass-1",
        role_code="staff",
    )

    assert review.display_name == "Mike Shaw"
    assert review.role_code == "staff"


def test_build_operator_onboard_review_rejects_dev_role():
    with pytest.raises(ValueError):
        svc.build_operator_onboard_review(
            first_name="Michael",
            last_name="Shaw",
            preferred_name="Mike",
            username="mshaw",
            email=None,
            temporary_password="temp-pass-1",
            role_code="dev",
        )


def test_commit_operator_onboard_orchestrates_entity_then_auth(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    class _Created:
        entity_ulid = "01AAAAAAAAAAAAAAAAAAAAAAAA"
        display_name = "Mike Shaw"

    def fake_create_operator_core(**kwargs):
        calls.append(("entity", kwargs))
        return _Created()

    def fake_create_account(**kwargs):
        calls.append(("auth", kwargs))
        return {
            "ulid": "01BBBBBBBBBBBBBBBBBBBBBBBB",
            "username": kwargs["username"],
        }

    monkeypatch.setattr(
        svc.entity_v2,
        "create_operator_core",
        fake_create_operator_core,
    )
    monkeypatch.setattr(
        svc.auth_v1,
        "create_account",
        fake_create_account,
    )

    result = svc.commit_operator_onboard(
        first_name="Michael",
        last_name="Shaw",
        preferred_name="Mike",
        username="mshaw",
        email="mshaw@example.test",
        temporary_password="temp-pass-1",
        role_code="staff",
        actor_ulid="01ACTORACTORACTORACTORACT",
        request_id="01REQREQREQREQREQREQREQRE",
    )

    assert result.entity_ulid == "01AAAAAAAAAAAAAAAAAAAAAAAA"
    assert result.account_ulid == "01BBBBBBBBBBBBBBBBBBBBBBBB"
    assert calls[0][0] == "entity"
    assert calls[1][0] == "auth"
    assert calls[1][1]["roles"] == ["staff"]


def test_edit_operator_rbac_role_calls_single_role_assignment(monkeypatch):
    monkeypatch.setattr(
        svc.auth_v1,
        "set_account_roles",
        lambda account_ulid, roles: {
            "ulid": account_ulid,
            "username": "mshaw",
            "entity_ulid": None,
            "roles": list(roles),
        },
    )

    result = svc.edit_operator_rbac_role(
        account_ulid="01BBBBBBBBBBBBBBBBBBBBBBBB",
        role_code="admin",
    )

    assert result.role_code == "admin"
    assert result.username == "mshaw"
