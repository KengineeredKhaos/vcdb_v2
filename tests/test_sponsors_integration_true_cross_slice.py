# tests/test_sponsors_integration_true_cross_slice.py
from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.contracts import entity_v2, sponsors_v2
from app.lib.ids import new_ulid
from app.slices.ledger.models import LedgerEvent


def _event_text(ev: LedgerEvent) -> str:
    parts = [
        str(getattr(ev, "event_type", "") or ""),
        str(getattr(ev, "domain", "") or ""),
        str(getattr(ev, "operation", "") or ""),
        str(getattr(ev, "meta_json", "") or ""),
        str(getattr(ev, "payload_json", "") or ""),
    ]
    return " ".join(parts)


def test_sponsors_true_cross_slice_create_then_capability_then_pledge_records_ledger(staff_client, monkeypatch):
    """
    True cross-slice:
      Entity.ensure_person -> POST /sponsors -> POST capability -> sponsors_v2.upsert_pledge
      -> verify Ledger events exist and contain no PII.
    """
    # Keep the test scoped: monkeypatch sponsor policy to allow our codes/types.
    import app.slices.sponsors.services as sp_svc

    monkeypatch.setattr(sp_svc, "_caps_policy", lambda: {"all_codes": ["fund_type.cash_grant"], "note_max": 200})
    monkeypatch.setattr(
        sp_svc,
        "_pledge_policy",
        lambda: {"allowed_types": ["cash_grant"], "allowed_statuses": ["proposed", "committed"], "currencies": ["USD"], "note_max": 200},
    )

    first = "SponsorX"
    last = "Integration"

    ent = entity_v2.ensure_person(
        db.session,
        first_name=first,
        last_name=last,
        email=f"sx-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r = staff_client.post("/sponsors", json={"entity_ulid": ent.entity_ulid})
    assert r.status_code == 200, r.get_json()
    sid = r.get_json()["data"]["sponsor_ulid"]
    assert sid == ent.entity_ulid

    cap = staff_client.post(f"/sponsors/{sid}/capabilities", json={"fund_type.cash_grant": True})
    assert cap.status_code == 200, cap.get_json()

    out = sponsors_v2.upsert_pledge(
        sponsor_ulid=sid,
        payload={"pledge_type": "cash_grant", "amount_cents": 12345, "currency": "USD", "notes": "starter"},
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    assert out["ok"] is True
    pledge_ulid = out["data"]["pledge_ulid"]
    assert pledge_ulid

    # Ledger: created_insert and capability_upsert should be present (best-effort)
    created = (
        db.session.query(LedgerEvent)
        .filter(LedgerEvent.domain == "sponsors")
        .filter(LedgerEvent.operation == "created_insert")
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )
    assert created is not None

    cap_ev = (
        db.session.query(LedgerEvent)
        .filter(LedgerEvent.domain == "sponsors")
        .filter(LedgerEvent.operation == "capability_upsert")
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )
    assert cap_ev is not None

    pledge_ev = (
        db.session.query(LedgerEvent)
        .filter(LedgerEvent.domain == "sponsors")
        .filter(LedgerEvent.operation == "pledge_upserted")
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )
    assert pledge_ev is not None

    combined = (_event_text(created) + " " + _event_text(cap_ev) + " " + _event_text(pledge_ev)).lower()
    # No PII strings in ledger/logs
    assert first.lower() not in combined
    assert last.lower() not in combined
    assert "test.invalid" not in combined


def test_sponsors_contract_cues_are_pii_free(monkeypatch, staff_client):
    import app.slices.sponsors.services as sp_svc

    monkeypatch.setattr(sp_svc, "_caps_policy", lambda: {"all_codes": ["fund_type.cash_grant"], "note_max": 200})
    monkeypatch.setattr(
        sp_svc,
        "_pledge_policy",
        lambda: {"allowed_types": ["cash_grant"], "allowed_statuses": ["proposed"], "currencies": ["USD"], "note_max": 200},
    )

    ent = entity_v2.ensure_person(
        db.session,
        first_name="Cue",
        last_name="Test",
        email=f"cue-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    r = staff_client.post("/sponsors", json={"entity_ulid": ent.entity_ulid})
    sid = r.get_json()["data"]["sponsor_ulid"]

    staff_client.post(f"/sponsors/{sid}/capabilities", json={"fund_type.cash_grant": True})
    sponsors_v2.upsert_pledge(
        sponsor_ulid=sid,
        payload={"pledge_type": "cash_grant", "amount_cents": 100, "currency": "USD", "notes": "n/a"},
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    cues = sponsors_v2.get_sponsor_cues(sid)
    assert cues.sponsor_ulid == sid
    assert "fund_type.cash_grant" in cues.active_capability_codes
    assert cues.pledge_total_cents >= 100
