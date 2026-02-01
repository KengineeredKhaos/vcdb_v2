# tests/test_resources_integration_true_cross_slice.py
from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.contracts import entity_v2, governance_v2, resources_v2
from app.lib.ids import new_ulid
from app.slices.ledger.models import LedgerEvent


def _pick_cap_code(*, prefer_non_meta: bool = True) -> str:
    pol = governance_v2.get_resource_capabilities_policy()
    codes = list(getattr(pol, "all_codes", []) or [])
    assert (
        codes
    ), "Governance policy returned no resource capability codes (service_taxonomy)."

    if prefer_non_meta:
        for c in codes:
            if c != "meta.unclassified":
                return c
    return codes[0]


def _event_text(ev: LedgerEvent) -> str:
    # Try a few common JSON/text columns; tolerate schema drift.
    parts: list[str] = []
    for attr in (
        "refs_json",
        "data_json",
        "payload_json",
        "meta_json",
        "body_json",
    ):
        v = getattr(ev, attr, None)
        if v:
            parts.append(str(v))
    for attr in ("refs", "data", "meta"):
        v = getattr(ev, attr, None)
        if v:
            parts.append(str(v))
    return " ".join(parts)


def test_resources_true_cross_slice_entity_to_routes_to_contract_to_ledger(
    staff_client,
):
    """
    True cross-slice integration for Resources:

      Entity.ensure_person -> POST /resources -> POST /resources/<rid>/capabilities
      -> GET /resources?any=domain.key -> resources_v2.get_resource_view()
      -> LedgerEvent emitted (no PII)

    This does NOT monkeypatch Governance: capability codes come from governance_v2 policy.
    """
    # 1) Create a real Entity (exercise Entity slice write path)
    first = "XSliceRes"
    last = "Integration"
    email = f"xslice-res-{new_ulid()}@test.invalid"

    ent = entity_v2.ensure_person(
        db.session,
        first_name=first,
        last_name=last,
        email=email,
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    entity_ulid = ent.entity_ulid

    # 2) Ensure Resource via route (exercise Resources creation routine)
    r = staff_client.post("/resources", json={"entity_ulid": entity_ulid})
    assert r.status_code == 200, r.get_json()
    rid = r.get_json()["data"]["resource_ulid"]
    assert rid

    # 3) Upsert ONE capability code picked from Governance policy
    cap = _pick_cap_code(prefer_non_meta=True)
    up = staff_client.post(f"/resources/{rid}/capabilities", json={cap: True})
    assert up.status_code == 200, up.get_json()
    view = up.get_json()["data"]["resource"]
    assert view["resource_ulid"] == rid

    domain, key = cap.split(".", 1)
    assert {"domain": domain, "key": key} in (
        view.get("active_capabilities") or []
    )

    # 4) Search via route
    s = staff_client.get("/resources", query_string={"any": cap})
    assert s.status_code == 200, s.get_json()
    rows = s.get_json()["data"]["rows"]
    assert any(row["resource_ulid"] == rid for row in rows)

    # 5) Contract read is available + PII-free surface
    cv = resources_v2.get_resource_view(rid)
    assert cv["resource_ulid"] == rid
    assert {"domain": domain, "key": key} in (
        cv.get("active_capabilities") or []
    )

    # 6) Ledger events: at least created + capability_add should exist
    created = (
        db.session.query(LedgerEvent)
        .filter(
            LedgerEvent.domain == "resources",
            LedgerEvent.operation == "created_insert",
            LedgerEvent.target_ulid == rid,
        )
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )
    assert created is not None

    cap_add = (
        db.session.query(LedgerEvent)
        .filter(
            LedgerEvent.domain == "resources",
            LedgerEvent.operation == "capability_add",
            LedgerEvent.target_ulid == rid,
        )
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )
    assert cap_add is not None

    # 7) PII boundary smoke check: Resources events must not contain Entity PII strings
    # (names/emails should live only in Entity slice)
    combined = (_event_text(created) + " " + _event_text(cap_add)).lower()
    assert first.lower() not in combined
    assert last.lower() not in combined
    assert "test.invalid" not in combined


def test_resources_rejects_unknown_capability_code_from_policy(staff_client):
    """Unknown capability codes must be rejected (policy-backed allowlist)."""
    ent = entity_v2.ensure_person(
        db.session,
        first_name="Bad",
        last_name="Cap",
        email=f"bad-cap-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r = staff_client.post("/resources", json={"entity_ulid": ent.entity_ulid})
    assert r.status_code == 200, r.get_json()
    rid = r.get_json()["data"]["resource_ulid"]

    resp = staff_client.post(
        f"/resources/{rid}/capabilities", json={"does.notexist": True}
    )
    assert resp.status_code == 400, resp.get_json()
    body = resp.get_json() or {}
    assert body.get("ok") is False
    assert "unknown capability" in (body.get("error") or "").lower()


def test_resources_meta_unclassified_triggers_admin_review_when_present(
    staff_client,
):
    """
    If Governance policy includes meta.unclassified, setting it active should flip admin_review_required.
    """
    pol = governance_v2.get_resource_capabilities_policy()
    codes = set(getattr(pol, "all_codes", []) or [])
    if "meta.unclassified" not in codes:
        pytest.skip(
            "meta.unclassified not present in service_taxonomy policy"
        )

    ent = entity_v2.ensure_person(
        db.session,
        first_name="Meta",
        last_name="Unclassified",
        email=f"meta-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r = staff_client.post("/resources", json={"entity_ulid": ent.entity_ulid})
    assert r.status_code == 200, r.get_json()
    rid = r.get_json()["data"]["resource_ulid"]

    up = staff_client.post(
        f"/resources/{rid}/capabilities", json={"meta.unclassified": True}
    )
    assert up.status_code == 200, up.get_json()
    view = up.get_json()["data"]["resource"]
    assert view["admin_review_required"] is True
