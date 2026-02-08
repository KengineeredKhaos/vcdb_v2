"""Integration tests for Resources slice using real HTTP routes.

These are "true cross-slice" in the sense that they create an Entity via the
Entity contract, then exercise Resources routes, and finally inspect the Ledger.

Facet invariant:
- Resource is a facet table keyed by entity_ulid (Resource PK == Entity.ulid).
"""

from __future__ import annotations

import json

from app.extensions import db
from app.extensions.contracts import entity_v2
from app.lib.ids import new_ulid
from app.slices.ledger.models import LedgerEvent


def _assert_ok(resp) -> dict:
    assert resp.status_code == 200, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert payload and payload.get("ok") is True
    assert "data" in payload
    # request_id is now part of the canonical response envelope for slice routes
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
        # payload_json can be stored as a JSON string in some migrations
        return str(ev.payload_json)


def test_resources_routes_registered(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    # minimal surface
    assert "/resources" in rules
    assert "/resources/<resource_ulid>/capabilities" in rules


def test_resources_true_cross_slice_route_flow(staff_client):
    # Create an org entity (outside the Resources slice), then create its Resource facet.
    org = entity_v2.ensure_org(
        db.session,
        org_name="VC Test Resource Org",
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r = staff_client.post("/resources", json={"entity_ulid": org.entity_ulid})
    data = _assert_ok(r)

    rid = data["resource_ulid"]
    # Facet PK == Entity.ulid
    assert rid == org.entity_ulid

    # Replace (upsert) capabilities
    cap_payload = {
        "basic_needs.food_pantry": {"has": True, "note": "open daily"},
        "events.stand_down": True,
    }
    r2 = staff_client.post(f"/resources/{rid}/capabilities", json=cap_payload)
    data2 = _assert_ok(r2)
    assert data2["resource"]["resource_entity_ulid"] == rid
    assert {
        c["domain"] + "." + c["key"]
        for c in data2["resource"]["active_capabilities"]
    } >= {
        "basic_needs.food_pantry",
        "events.stand_down",
    }

    # Ledger: should record resource creation and capability changes (no PII)
    ev = _latest_event(rid)
    txt = _event_text(ev)
    assert "VC Test Resource Org" not in txt  # no org name in ledger

    # We expect at least one resources.* event
    assert "resources." in txt
