# test_sponsors_integration_true_cross_slice.py

from __future__ import annotations

import json
from types import SimpleNamespace

from app.extensions import db
from app.lib.ids import new_ulid
from app.extensions.contracts.entity_v2 import entity_v2
from app.slices.ledger.models import LedgerEvent


def _assert_ok(resp):
    assert resp.status_code == 200, resp.get_json()
    payload = resp.get_json()
    assert payload and payload.get("ok") is True, payload
    assert "data" in payload and isinstance(payload["data"], dict), payload
    # Your canonical route contract includes request_id
    assert payload.get("request_id"), payload
    return payload


def _assert_sponsor_routes_present(client):
    rules = {r.rule for r in client.application.url_map.iter_rules()}
    # Minimal surface we expect
    assert "/sponsors" in rules
    assert "/sponsors/<sponsor_entity_ulid>" in rules
    assert "/sponsors/<sponsor_entity_ulid>/capabilities" in rules
    assert "/sponsors/<sponsor_entity_ulid>/pledges" in rules


def _ensure_org_entity_ulid() -> str:
    ent = entity_v2.ensure_org(
        db.session,
        legal_name=f"Sponsor Org {new_ulid()}",
        email=f"sx-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    return ent.entity_ulid


def test_sponsors_true_cross_slice_create_then_capability_then_pledge_records_ledger(
    staff_client, monkeypatch
):
    """
    True cross-slice:
      Entity.ensure_org -> POST /sponsors -> POST capability -> POST pledge
      -> verify Ledger events exist and contain no PII.
    """
    _assert_sponsor_routes_present(staff_client)

    import app.slices.sponsors.services as sp_svc

    # Sponsor capability policy: service expects an object with attrs (.all_codes, .note_max)
    monkeypatch.setattr(
        sp_svc,
        "_caps_policy",
        lambda: SimpleNamespace(
            all_codes=["fund_type.cash_grant"], note_max=200
        ),
    )

    # Pledge policy: service expects dict with types/statuses lists of {code: ...}
    monkeypatch.setattr(
        sp_svc,
        "_pledge_policy",
        lambda: {
            "types": [{"code": "cash"}, {"code": "in_kind"}],
            "statuses": [{"code": "proposed"}, {"code": "committed"}],
            "note_max": 200,
        },
    )

    entity_ulid = _ensure_org_entity_ulid()

    # 1) Create sponsor facet row
    r = staff_client.post("/sponsors", json={"entity_ulid": entity_ulid})
    payload = _assert_ok(r)
    sid = payload["data"]["sponsor_entity_ulid"]

    # Facet invariant: sponsor PK == entity_ulid
    assert sid == entity_ulid

    # 2) Add capability
    r = staff_client.post(
        f"/sponsors/{sid}/capabilities",
        json={
            "capabilities": [{"code": "fund_type.cash_grant", "has": True}]
        },
    )
    _assert_ok(r)

    # 3) Add pledge
    r = staff_client.post(
        f"/sponsors/{sid}/pledges",
        json={
            "type": "cash",
            "status": "proposed",
            "has_restriction": False,
            "est_value_number": 25000,
            "currency": "USD",
        },
    )
    pledge_payload = _assert_ok(r)
    pledge_ulid = pledge_payload["data"]["pledge_ulid"]
    assert pledge_ulid and len(pledge_ulid) == 26

    # 4) Verify sponsor view is PII-free and includes our signals
    r = staff_client.get(f"/sponsors/{sid}")
    view_payload = _assert_ok(r)
    view = view_payload["data"]

    assert view["sponsor_entity_ulid"] == sid
    # If you include entity_ulid in the view, it must match too:
    if "entity_ulid" in view:
        assert view["entity_ulid"] == sid

    # Make sure capability shows up in some form
    caps_text = json.dumps(view)
    assert "fund_type" in caps_text and "cash_grant" in caps_text

    # 5) Verify Ledger events exist and contain no PII
    events = (
        db.session.query(LedgerEvent)
        .filter_by(domain="sponsors", target_ulid=sid)
        .order_by(LedgerEvent.happened_at_utc.asc())
        .all()
    )
    assert events, "Expected at least one sponsors LedgerEvent"

    # No PII: should not leak names/emails from the entity row
    pii_markers = ["Sponsor Org", "@test.invalid"]
    for ev in events:
        blob = (ev.payload_json or "") + " " + (ev.refs_json or "")
        for marker in pii_markers:
            assert (
                marker not in blob
            ), f"PII marker '{marker}' leaked into ledger event"


def test_sponsors_get_view_has_no_pii(staff_client, monkeypatch):
    import app.slices.sponsors.services as sp_svc

    monkeypatch.setattr(
        sp_svc,
        "_caps_policy",
        lambda: SimpleNamespace(
            all_codes=["fund_type.cash_grant"], note_max=200
        ),
    )
    monkeypatch.setattr(
        sp_svc,
        "_pledge_policy",
        lambda: {
            "types": [{"code": "cash"}],
            "statuses": [{"code": "proposed"}],
            "note_max": 200,
        },
    )

    entity_ulid = _ensure_org_entity_ulid()
    r = staff_client.post("/sponsors", json={"entity_ulid": entity_ulid})
    sid = _assert_ok(r)["data"]["sponsor_entity_ulid"]

    r = staff_client.get(f"/sponsors/{sid}")
    payload = _assert_ok(r)

    # Response should never include entity core PII (names/emails/phones)
    blob = json.dumps(payload)
    assert "@test.invalid" not in blob
    assert "legal_name" not in blob
