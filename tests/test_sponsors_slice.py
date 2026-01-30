# tests/test_sponsors_slice.py
from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import entity_v2, sponsors_v2
from app.lib.ids import new_ulid


def _monkeypatch_policies(monkeypatch):
    """
    Keep Sponsors tests focused by monkeypatching Governance policy access.
    """
    import app.slices.sponsors.services as sp_svc

    monkeypatch.setattr(
        sp_svc,
        "_lifecycle_policy",
        lambda: {
            "readiness_allowed": ["draft", "review", "active", "suspended"],
            "mou_allowed": [
                "none",
                "pending",
                "active",
                "expired",
                "terminated",
            ],
        },
    )
    monkeypatch.setattr(
        sp_svc,
        "_caps_policy",
        lambda: {
            "all_codes": ["fund_type.cash_grant", "meta.unclassified"],
            "note_max": 200,
        },
    )
    monkeypatch.setattr(
        sp_svc,
        "_pledge_policy",
        lambda: {
            "allowed_types": ["cash_grant", "restricted_grant"],
            "allowed_statuses": [
                "proposed",
                "committed",
                "received",
                "cancelled",
            ],
            "currencies": ["USD"],
            "note_max": 200,
        },
    )


def _ensure_any_entity_ulid():
    """
    Prefer org if contract supports it; fallback to person.
    We only need a real entity row to satisfy FK.
    """
    if hasattr(entity_v2, "ensure_org"):
        try:
            ent = entity_v2.ensure_org(
                db.session,
                name=f"Test Sponsor Org {new_ulid()}",
                email=f"org-{new_ulid()}@test.invalid",
                phone=None,
                request_id=new_ulid(),
                actor_ulid="seed",
            )
            return ent.entity_ulid
        except TypeError:
            pass

    ent = entity_v2.ensure_person(
        db.session,
        first_name="Sponsor",
        last_name="Entity",
        email=f"sponsor-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    return ent.entity_ulid


def test_sponsors_ensure_sponsor_idempotent(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()

    r1 = staff_client.post("/sponsors", json={"entity_ulid": ent_ulid})
    assert r1.status_code == 200, r1.get_json()
    sid = r1.get_json()["data"]["sponsor_ulid"]
    assert sid

    r2 = staff_client.post("/sponsors", json={"entity_ulid": ent_ulid})
    assert r2.status_code == 200, r2.get_json()
    sid2 = r2.get_json()["data"]["sponsor_ulid"]
    assert sid2 == sid


def test_sponsors_upsert_capabilities_writes_history_and_index(
    monkeypatch, staff_client
):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    sid = staff_client.post(
        "/sponsors", json={"entity_ulid": ent_ulid}
    ).get_json()["data"]["sponsor_ulid"]

    up = staff_client.post(
        f"/sponsors/{sid}/capabilities",
        json={"fund_type.cash_grant": True},
    )
    assert up.status_code == 200, up.get_json()
    data = up.get_json()["data"]
    assert "history_ulid" in data
    view = data["sponsor"]
    assert {"domain": "fund_type", "key": "cash_grant"} in (
        view.get("active_capabilities") or []
    )

    # Contract read view works and is PII-free
    v = sponsors_v2.get_sponsor_view(sid)
    assert v["sponsor_ulid"] == sid


def test_sponsors_patch_note_only_does_not_flip_has(
    monkeypatch, staff_client
):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    sid = staff_client.post(
        "/sponsors", json={"entity_ulid": ent_ulid}
    ).get_json()["data"]["sponsor_ulid"]

    sponsors_v2.upsert_capabilities(
        sponsor_ulid=sid,
        capabilities={"fund_type.cash_grant": False},
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    # note-only patch should NOT change has=False
    sponsors_v2.patch_capabilities(
        sponsor_ulid=sid,
        capabilities={"fund_type.cash_grant": {"note": "restricted to Q2"}},
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    view = sponsors_v2.get_sponsor_view(sid)
    assert {"domain": "fund_type", "key": "cash_grant"} not in (
        view.get("active_capabilities") or []
    )


def test_sponsors_promote_if_clean(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    sid = staff_client.post(
        "/sponsors", json={"entity_ulid": ent_ulid}
    ).get_json()["data"]["sponsor_ulid"]

    sponsors_v2.upsert_capabilities(
        sponsor_ulid=sid,
        capabilities={"fund_type.cash_grant": True},
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    view = sponsors_v2.get_sponsor_view(sid)
    assert view["readiness_status"] in ("draft", "review", "active")

    out = sponsors_v2.promote_if_clean(
        sponsor_ulid=sid,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    assert out["ok"] is True

    view2 = sponsors_v2.get_sponsor_view(sid)
    assert view2["readiness_status"] in ("draft", "review", "active")


def test_sponsors_search_by_capability(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    sid = staff_client.post(
        "/sponsors", json={"entity_ulid": ent_ulid}
    ).get_json()["data"]["sponsor_ulid"]
    staff_client.post(
        f"/sponsors/{sid}/capabilities", json={"fund_type.cash_grant": True}
    )

    resp = staff_client.get(
        "/sponsors", query_string={"any": "fund_type.cash_grant"}
    )
    assert resp.status_code == 200, resp.get_json()
    rows = resp.get_json()["data"]["rows"]
    assert any(r["sponsor_ulid"] == sid for r in rows)


def test_sponsors_pledge_create_and_status_update(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    sid = staff_client.post(
        "/sponsors", json={"entity_ulid": ent_ulid}
    ).get_json()["data"]["sponsor_ulid"]

    out = sponsors_v2.upsert_pledge(
        sponsor_ulid=sid,
        payload={
            "pledge_type": "cash_grant",
            "amount_cents": 25000,
            "currency": "USD",
            "notes": "FY26 starter",
        },
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    pledge_ulid = out["data"]["pledge_ulid"]
    assert pledge_ulid

    out2 = sponsors_v2.set_pledge_status(
        sponsor_ulid=sid,
        pledge_ulid=pledge_ulid,
        status="committed",
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    assert out2["ok"] is True
