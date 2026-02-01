# test_sponsors_slice.py

from __future__ import annotations

from types import SimpleNamespace

from app.extensions import db
from app.lib.ids import new_ulid
from app.extensions.contracts.entity_v2 import entity_v2


def _assert_ok(resp):
    assert resp.status_code == 200, resp.get_json()
    payload = resp.get_json()
    assert payload and payload.get("ok") is True, payload
    assert payload.get("request_id"), payload
    assert "data" in payload and isinstance(payload["data"], dict), payload
    return payload["data"]


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


def _patch_policies(monkeypatch):
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
            "types": [{"code": "cash"}, {"code": "in_kind"}],
            "statuses": [{"code": "proposed"}, {"code": "committed"}],
            "note_max": 200,
        },
    )


def test_sponsors_ensure_upsert_caps_then_search(staff_client, monkeypatch):
    _patch_policies(monkeypatch)

    entity_ulid = _ensure_org_entity_ulid()

    # ensure sponsor facet
    data = _assert_ok(
        staff_client.post("/sponsors", json={"entity_ulid": entity_ulid})
    )
    sid = data["sponsor_entity_ulid"]
    assert sid == entity_ulid  # facet invariant

    # upsert capabilities
    data = _assert_ok(
        staff_client.post(
            f"/sponsors/{sid}/capabilities",
            json={
                "capabilities": [
                    {"code": "fund_type.cash_grant", "has": True}
                ]
            },
        )
    )
    assert data.get("history_ulid")

    # search sponsors by capability
    data = _assert_ok(
        staff_client.get(
            "/sponsors", query_string={"any": "fund_type.cash_grant"}
        )
    )
    assert data["total"] >= 1
    assert any(
        (row.get("sponsor_entity_ulid") == sid) for row in data["rows"]
    )


def test_sponsors_set_readiness_and_mou(staff_client, monkeypatch):
    _patch_policies(monkeypatch)

    entity_ulid = _ensure_org_entity_ulid()
    sid = _assert_ok(
        staff_client.post("/sponsors", json={"entity_ulid": entity_ulid})
    )["sponsor_entity_ulid"]

    data = _assert_ok(
        staff_client.post(
            f"/sponsors/{sid}/readiness", json={"status": "review"}
        )
    )
    assert data["readiness_status"] == "review"

    data = _assert_ok(
        staff_client.post(f"/sponsors/{sid}/mou", json={"status": "pending"})
    )
    assert data["mou_status"] == "pending"


def test_sponsors_pledge_then_status_update(staff_client, monkeypatch):
    _patch_policies(monkeypatch)

    entity_ulid = _ensure_org_entity_ulid()
    sid = _assert_ok(
        staff_client.post("/sponsors", json={"entity_ulid": entity_ulid})
    )["sponsor_entity_ulid"]

    data = _assert_ok(
        staff_client.post(
            f"/sponsors/{sid}/pledges",
            json={
                "type": "cash",
                "status": "proposed",
                "est_value_number": 10000,
                "currency": "USD",
            },
        )
    )
    pledge_ulid = data["pledge_ulid"]
    assert pledge_ulid and len(pledge_ulid) == 26

    data = _assert_ok(
        staff_client.post(
            f"/sponsors/pledges/{pledge_ulid}/status",
            json={"status": "committed"},
        )
    )
    assert data["pledge_ulid"] == pledge_ulid
    assert data["status"] == "committed"
