"""Integration tests for Sponsors slice using real HTTP routes.

These are "true cross-slice" in the sense that they create a Person Entity via
the Entity contract, then exercise Sponsors routes, and finally inspect the Ledger.

Facet invariant:
- Sponsor is a facet table keyed by entity_ulid (Sponsor PK == Entity.ulid).
"""

from __future__ import annotations

import json

import pytest

from app.extensions import db
from app.extensions.contracts import entity_v2
from app.lib.ids import new_ulid
from app.slices.ledger.models import LedgerEvent


def _assert_ok(resp) -> dict:
    assert resp.status_code == 200, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert payload and payload.get("ok") is True
    assert "data" in payload
    assert "request_id" in payload
    return payload["data"]


def _latest_event(target_ulid: str) -> LedgerEvent:
    q = (
        db.session.query(LedgerEvent)
        .filter(LedgerEvent.target_ulid == target_ulid)
        .order_by(LedgerEvent.happened_at_utc.desc())
    )
    ev = q.first()
    assert ev is not None
    return ev


def _event_text(ev: LedgerEvent) -> str:
    try:
        return json.dumps(ev.payload_json, sort_keys=True)
    except Exception:
        return str(ev.payload_json)


def test_sponsor_routes_registered(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/sponsors" in rules
    assert "/sponsors/<sponsor_entity_ulid>" in rules
    assert "/sponsors/<sponsor_entity_ulid>/capabilities" in rules
    assert "/sponsors/<sponsor_entity_ulid>/pledges" in rules
    assert "/sponsors/pledges/<pledge_ulid>/status" in rules


def test_sponsors_true_cross_slice_route_flow(monkeypatch, staff_client):
    # Make policy deterministic and local to the test.
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

    # Create a Person entity with PII so we can verify it never lands in the Ledger.
    ent = entity_v2.ensure_person(
        db.session,
        first_name="Test",
        last_name="Sponsor",
        email="test.sponsor@example.org",
        phone="555-0101",
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r = staff_client.post("/sponsors", json={"entity_ulid": ent.entity_ulid})
    data = _assert_ok(r)

    sid = data["sponsor_entity_ulid"]
    assert sid == ent.entity_ulid  # facet PK

    # Upsert capabilities
    r2 = staff_client.post(
        f"/sponsors/{sid}/capabilities",
        json={"fund_type.cash_grant": True},
    )
    data2 = _assert_ok(r2)
    assert data2["sponsor"]["sponsor_entity_ulid"] == sid

    # Upsert pledge (requires pledge_ulid)
    pledge_ulid = new_ulid()
    pledge_payload = {
        "pledge_ulid": pledge_ulid,
        "type": "cash",
        "status": "active",
        "currency": "USD",
        "stated_amount": 123_45,
        "notes": "seed pledge",
    }
    r3 = staff_client.post(f"/sponsors/{sid}/pledges", json=pledge_payload)
    data3 = _assert_ok(r3)
    assert data3["pledge_ulid"] == pledge_ulid

    # Update pledge status
    r4 = staff_client.post(
        f"/sponsors/pledges/{pledge_ulid}/status",
        json={"status": "fulfilled"},
    )
    data4 = _assert_ok(r4)
    assert data4["status"] == "fulfilled"

    # Ledger: should contain sponsor events but not person PII (name/email/phone).
    ev = _latest_event(sid)
    txt = _event_text(ev)
    assert "Test" not in txt
    assert "Sponsor" not in txt
    assert "test.sponsor@example.org" not in txt
    assert "555-0101" not in txt
    assert "sponsors." in txt
