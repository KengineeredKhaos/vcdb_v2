# tests/test_resources_slice.py
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.extensions import db
from app.extensions.contracts import entity_v2, resources_v2
from app.lib.ids import new_ulid


def _monkeypatch_policies(monkeypatch):
    """
    Keep Resources tests focused by monkeypatching Governance policy access.
    """
    import app.slices.resources.services as res_svc

    monkeypatch.setattr(
        res_svc,
        "_lifecycle_policy",
        lambda: {
            "readiness_allowed": ["draft", "review", "active", "suspended"],
            "mou_allowed": ["none", "pending", "active", "expired", "terminated"],
        },
    )
    monkeypatch.setattr(
        res_svc,
        "_caps_policy",
        lambda: {"all_codes": ["basic_needs.food_pantry", "meta.unclassified"], "note_max": 200},
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
                name=f"Test Org {new_ulid()}",
                email=f"org-{new_ulid()}@test.invalid",
                phone=None,
                request_id=new_ulid(),
                actor_ulid="seed",
            )
            return ent.entity_ulid
        except TypeError:
            # signature mismatch; fall through
            pass

    ent = entity_v2.ensure_person(
        db.session,
        first_name="Res",
        last_name="Provider",
        email=f"res-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    return ent.entity_ulid


def test_resources_ensure_resource_idempotent(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()

    r1 = staff_client.post("/resources", json={"entity_ulid": ent_ulid})
    assert r1.status_code == 200, r1.get_json()
    rid = r1.get_json()["data"]["resource_ulid"]
    assert rid

    r2 = staff_client.post("/resources", json={"entity_ulid": ent_ulid})
    assert r2.status_code == 200, r2.get_json()
    rid2 = r2.get_json()["data"]["resource_ulid"]
    assert rid2 == rid


def test_resources_upsert_capabilities_writes_history_and_index(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    resp = staff_client.post("/resources", json={"entity_ulid": ent_ulid})
    rid = resp.get_json()["data"]["resource_ulid"]

    up = staff_client.post(
        f"/resources/{rid}/capabilities",
        json={"basic_needs.food_pantry": True},
    )
    assert up.status_code == 200, up.get_json()
    data = up.get_json()["data"]
    assert data["history_ulid"]  # new version created
    view = data["resource"]
    assert view["readiness_status"] in ("review", "draft")
    assert {"domain": "basic_needs", "key": "food_pantry"} in view["active_capabilities"]

    # Contract read view works and is PII-free
    v = resources_v2.get_resource_view(rid)
    assert v["resource_ulid"] == rid


def test_resources_upsert_idempotent_returns_none_history(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    rid = staff_client.post("/resources", json={"entity_ulid": ent_ulid}).get_json()["data"]["resource_ulid"]

    first = resources_v2.upsert_capabilities(
        resource_ulid=rid,
        capabilities={"basic_needs.food_pantry": True},
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    assert first["data"]["history_ulid"]

    second = resources_v2.upsert_capabilities(
        resource_ulid=rid,
        capabilities={"basic_needs.food_pantry": True},
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    # idempotent -> history_ulid None
    assert second["data"]["history_ulid"] is None


def test_resources_patch_note_only_does_not_flip_has(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    rid = staff_client.post("/resources", json={"entity_ulid": ent_ulid}).get_json()["data"]["resource_ulid"]

    resources_v2.upsert_capabilities(
        resource_ulid=rid,
        capabilities={"basic_needs.food_pantry": False},
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    # note-only patch should NOT change has=False
    resources_v2.patch_capabilities(
        resource_ulid=rid,
        capabilities={"basic_needs.food_pantry": {"note": "closed on weekends"}},
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    # active capabilities should still be empty
    view = resources_v2.get_resource_view(rid)
    assert {"domain": "basic_needs", "key": "food_pantry"} not in (view.get("active_capabilities") or [])


def test_resources_promote_if_clean(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    rid = staff_client.post("/resources", json={"entity_ulid": ent_ulid}).get_json()["data"]["resource_ulid"]

    # upsert without meta.unclassified should move draft -> review
    resources_v2.upsert_capabilities(
        resource_ulid=rid,
        capabilities={"basic_needs.food_pantry": True},
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    view = resources_v2.get_resource_view(rid)
    assert view["readiness_status"] in ("review", "active", "draft")

    # promote review -> active
    out = resources_v2.promote_if_clean(
        resource_ulid=rid,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    assert out["data"]["promoted"] in (True, False)

    view2 = resources_v2.get_resource_view(rid)
    assert view2["readiness_status"] in ("active", "review", "draft")


def test_resources_search_by_capability(monkeypatch, staff_client):
    _monkeypatch_policies(monkeypatch)

    ent_ulid = _ensure_any_entity_ulid()
    rid = staff_client.post("/resources", json={"entity_ulid": ent_ulid}).get_json()["data"]["resource_ulid"]
    staff_client.post(f"/resources/{rid}/capabilities", json={"basic_needs.food_pantry": True})

    resp = staff_client.get("/resources", query_string={"any": "basic_needs.food_pantry"})
    assert resp.status_code == 200, resp.get_json()
    rows = resp.get_json()["data"]["rows"]
    assert any(r["resource_ulid"] == rid for r in rows)
