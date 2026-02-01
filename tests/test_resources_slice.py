"""Resources slice route tests.

These tests focus on the HTTP surface (routes + services + commit/rollback).
They intentionally avoid reaching into contracts directly so they smoke out:
- parsing / validation issues
- response envelope shape
- facet key correctness (resource_ulid == entity_ulid)
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.contracts import entity_v2
from app.lib.ids import new_ulid
from app.slices.resources.models import Resource


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


def test_resources_ensure_requires_entity_ulid(staff_client):
    resp = staff_client.post("/resources", json={})
    _assert_err(resp, 400)


def test_resources_ensure_idempotent(staff_client):
    org = entity_v2.ensure_org(
        db.session,
        org_name="VC Test Org (resources idempotent)",
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r1 = staff_client.post("/resources", json={"entity_ulid": org.entity_ulid})
    d1 = _assert_ok(r1)
    rid1 = d1["resource_ulid"]
    assert rid1 == org.entity_ulid

    r2 = staff_client.post("/resources", json={"entity_ulid": org.entity_ulid})
    d2 = _assert_ok(r2)
    rid2 = d2["resource_ulid"]
    assert rid2 == rid1

    # Only one facet row exists
    assert db.session.query(Resource).filter_by(entity_ulid=org.entity_ulid).count() == 1


def test_resources_capabilities_roundtrip(staff_client):
    org = entity_v2.ensure_org(
        db.session,
        org_name="VC Test Org (resources caps)",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    rid = _assert_ok(
        staff_client.post("/resources", json={"entity_ulid": org.entity_ulid})
    )["resource_ulid"]

    # Set two capabilities
    cap_payload = {
        "basic_needs.food_pantry": True,
        "events.stand_down": True,
    }
    r1 = staff_client.post(f"/resources/{rid}/capabilities", json=cap_payload)
    d1 = _assert_ok(r1)
    codes1 = {c["domain"] + "." + c["key"] for c in d1["resource"]["active_capabilities"]}
    assert codes1 == {"basic_needs.food_pantry", "events.stand_down"}

    # Replace with a single capability (acts like replace)
    cap_payload2 = {"events.stand_down": True}
    r2 = staff_client.post(f"/resources/{rid}/capabilities", json=cap_payload2)
    d2 = _assert_ok(r2)
    codes2 = {c["domain"] + "." + c["key"] for c in d2["resource"]["active_capabilities"]}
    assert codes2 == {"events.stand_down"}


def test_resources_search_any(staff_client):
    org = entity_v2.ensure_org(
        db.session,
        org_name="VC Test Org (resources search)",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    rid = _assert_ok(
        staff_client.post("/resources", json={"entity_ulid": org.entity_ulid})
    )["resource_ulid"]
    staff_client.post(
        f"/resources/{rid}/capabilities",
        json={"events.stand_down": True},
    )

    r = staff_client.get("/resources", query_string={"any": "events.stand_down"})
    d = _assert_ok(r)
    assert d["total"] >= 1
    assert any(row.get("resource_entity_ulid") == rid for row in d["rows"])


def test_resources_rejects_bad_capability_code(staff_client):
    org = entity_v2.ensure_org(
        db.session,
        org_name="VC Test Org (bad cap code)",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    rid = _assert_ok(
        staff_client.post("/resources", json={"entity_ulid": org.entity_ulid})
    )["resource_ulid"]

    # Missing '.' should be rejected by parsing/validation
    resp = staff_client.post(f"/resources/{rid}/capabilities", json={"badcode": True})
    _assert_err(resp, 400)
