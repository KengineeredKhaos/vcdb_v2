"""Sponsors slice route tests.

These tests focus on the HTTP surface (routes + services + commit/rollback).
They are designed to catch:
- facet key drift (sponsor_entity_ulid == entity_ulid)
- response envelope drift (ok/request_id/data)
- validation regressions (caps / pledge payload)
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.contracts import entity_v2
from app.lib.ids import new_ulid
from app.slices.sponsors.models import Sponsor


def _assert_ok(resp) -> dict:
    assert resp.status_code == 200, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert payload and payload.get("ok") is True
    assert "data" in payload
    assert "request_id" in payload
    return payload["data"]


def _assert_err(resp, status: int) -> dict:
    assert resp.status_code == status, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert payload and payload.get("ok") is False
    return payload


@pytest.fixture()
def sponsor_policy(monkeypatch):
    """Make Sponsor policy deterministic so tests don't depend on governance seeds."""

    from app.slices.sponsors import services as sp_svc

    monkeypatch.setattr(
        sp_svc,
        "_caps_policy",
        lambda: {"all_codes": ["fund_type.cash_grant", "in_kind.goods"]},
    )
    monkeypatch.setattr(
        sp_svc,
        "_pledge_policy",
        lambda: {
            "types": [{"code": "cash"}, {"code": "in_kind"}],
            "statuses": [
                {"code": "proposed"},
                {"code": "active"},
                {"code": "fulfilled"},
                {"code": "cancelled"},
            ],
        },
    )


def test_sponsors_ensure_requires_entity_ulid(staff_client):
    resp = staff_client.post("/sponsors", json={})
    _assert_err(resp, 400)


def test_sponsors_ensure_idempotent(sponsor_policy, staff_client):
    person = entity_v2.ensure_person(
        db.session,
        first_name="Idem",
        last_name="Sponsor",
        email="idem.sponsor@example.org",
        phone="555-0102",
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r1 = staff_client.post(
        "/sponsors", json={"entity_ulid": person.entity_ulid}
    )
    d1 = _assert_ok(r1)
    sid1 = d1["sponsor_entity_ulid"]
    assert sid1 == person.entity_ulid

    r2 = staff_client.post(
        "/sponsors", json={"entity_ulid": person.entity_ulid}
    )
    d2 = _assert_ok(r2)
    sid2 = d2["sponsor_entity_ulid"]
    assert sid2 == sid1

    assert (
        db.session.query(Sponsor)
        .filter_by(entity_ulid=person.entity_ulid)
        .count()
        == 1
    )


def test_sponsors_capabilities_roundtrip(sponsor_policy, staff_client):
    person = entity_v2.ensure_person(
        db.session,
        first_name="Cap",
        last_name="Sponsor",
        email="cap.sponsor@example.org",
        phone="555-0103",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    sid = _assert_ok(
        staff_client.post(
            "/sponsors", json={"entity_ulid": person.entity_ulid}
        )
    )["sponsor_entity_ulid"]

    r1 = staff_client.post(
        f"/sponsors/{sid}/capabilities",
        json={"fund_type.cash_grant": True},
    )
    d1 = _assert_ok(r1)
    caps = {
        c["domain"] + "." + c["key"]
        for c in d1["sponsor"]["active_capabilities"]
    }
    assert caps == {"fund_type.cash_grant"}


def test_sponsors_readiness_and_mou(sponsor_policy, staff_client):
    person = entity_v2.ensure_person(
        db.session,
        first_name="Ready",
        last_name="Sponsor",
        email="ready.sponsor@example.org",
        phone="555-0104",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    sid = _assert_ok(
        staff_client.post(
            "/sponsors", json={"entity_ulid": person.entity_ulid}
        )
    )["sponsor_entity_ulid"]

    r1 = staff_client.post(
        f"/sponsors/{sid}/readiness", json={"status": "active"}
    )
    d1 = _assert_ok(r1)
    assert d1["readiness_status"] == "active"

    r2 = staff_client.post(f"/sponsors/{sid}/mou", json={"status": "pending"})
    d2 = _assert_ok(r2)
    assert d2["mou_status"] == "pending"


def test_sponsors_pledges_and_status(sponsor_policy, staff_client):
    person = entity_v2.ensure_person(
        db.session,
        first_name="Pledge",
        last_name="Sponsor",
        email="pledge.sponsor@example.org",
        phone="555-0105",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    sid = _assert_ok(
        staff_client.post(
            "/sponsors", json={"entity_ulid": person.entity_ulid}
        )
    )["sponsor_entity_ulid"]

    pledge_ulid = new_ulid()
    pledge = {
        "pledge_ulid": pledge_ulid,
        "type": "cash",
        "status": "active",
        "currency": "USD",
        "stated_amount": 50_00,
    }
    r1 = staff_client.post(f"/sponsors/{sid}/pledges", json=pledge)
    d1 = _assert_ok(r1)
    assert d1["pledge_ulid"] == pledge_ulid

    r2 = staff_client.post(
        f"/sponsors/pledges/{pledge_ulid}/status",
        json={"status": "fulfilled"},
    )
    d2 = _assert_ok(r2)
    assert d2["status"] == "fulfilled"


def test_sponsors_search_filters(sponsor_policy, staff_client):
    # Create one sponsor with capability and active pledge, then search.
    person = entity_v2.ensure_person(
        db.session,
        first_name="Search",
        last_name="Sponsor",
        email="search.sponsor@example.org",
        phone="555-0106",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    sid = _assert_ok(
        staff_client.post(
            "/sponsors", json={"entity_ulid": person.entity_ulid}
        )
    )["sponsor_entity_ulid"]

    staff_client.post(
        f"/sponsors/{sid}/capabilities", json={"fund_type.cash_grant": True}
    )
    staff_client.post(
        f"/sponsors/{sid}/pledges",
        json={
            "pledge_ulid": new_ulid(),
            "type": "cash",
            "status": "active",
            "currency": "USD",
            "stated_amount": 10_00,
        },
    )

    r = staff_client.get(
        "/sponsors",
        query_string={
            "any": "fund_type.cash_grant",
            "readiness": "draft",
            "has_active_pledges": "1",
        },
    )
    d = _assert_ok(r)
    assert d["total"] >= 1
    assert any(row.get("sponsor_entity_ulid") == sid for row in d["rows"])
