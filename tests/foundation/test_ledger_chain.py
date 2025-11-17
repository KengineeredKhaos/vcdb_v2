# tests/foundation/test_ledger_chain.py
import hashlib
import json

import pytest

from app.extensions import db, event_bus
from app.slices.ledger.models import LedgerEvent
from app.slices.ledger.services import verify_chain as verify_ledger


# tiny, stable json-compact helper (matches your services.dumps_compact output)
def _compact(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

def _rehash(prev_hex, env_dict):
    h = hashlib.sha256()
    if prev_hex:
        h.update(prev_hex.encode("utf-8"))
    h.update(_compact(env_dict).encode("utf-8"))
    return h.hexdigest()

@pytest.fixture(scope="module")
def _emit_some_events():
    """
    Use the *real* write-path: app.extensions.event_bus.emit(...).
    We emit across two chains to exercise partitioning.
    """
    rid = "REQTESTLEDGER000000000001"  # fixed request_id for determinism

    # Chain: "entity"
    event_bus.emit(
        domain="entity",
        operation="created",
        request_id=rid,
        actor_ulid=None,
        target_ulid="01EXAMPLEENTITYULID000000001",
        refs={"policy": {"version": "v1"}},
        changed={"fields": ["name"]},
        meta={"note": "smoke"},
        happened_at_utc=None,   # let service fill now_iso8601_ms()
        chain_key=None,         # default to domain
    )
    event_bus.emit(
        domain="entity",
        operation="role.assigned",
        request_id=rid,
        actor_ulid="01EXAMPLEADMINULID00000000001",
        target_ulid="01EXAMPLEENTITYULID000000001",
        refs=None,
        changed={"role": "customer"},
        meta=None,
        happened_at_utc=None,
        chain_key=None,
    )

    # Chain: "admin"
    event_bus.emit(
        domain="admin",
        operation="login.stub",
        request_id=rid,
        actor_ulid="01EXAMPLEADMINULID00000000001",
        target_ulid=None,
        refs=None,
        changed=None,
        meta={"mode": "stub"},
        happened_at_utc=None,
        chain_key=None,
    )

def test_verify_api_surface_ok(client, _emit_some_events):
    """
    Public service verifies (recomputes) the chains.
    We assert it reports ok and touched >0 events.
    """
    res_all = verify_ledger(None)
    assert res_all["ok"] is True
    assert res_all["checked"] >= 3
    assert "entity" in res_all["chains"]
    assert "admin" in res_all["chains"]

    # Optional: hit the route if mounted in testing
    r = client.get("/ledger/verify?chain_key=entity")
    if r.status_code == 200:
        j = r.get_json()
        assert j["ok"] is True
        assert "entity" in j["chains"]

def test_chain_links_and_hash_determinism(_emit_some_events):
    """
    Recompute exactly what services.verify_chain() computes, but from rows.
    This stays read-only and does not depend on private functions.
    """
    # Pull the rows in canonical order
    rows = (
        db.session.query(LedgerEvent)
        .order_by(LedgerEvent.chain_key.asc(), LedgerEvent.ulid.asc())
        .all()
    )
    assert rows, "expected at least one ledger event"

    prev_for = {}
    for ev in rows:
        # reconstruct the hashed envelope the same way services.verify_chain() does
        env = {
            "chain_key": ev.chain_key,
            "event_type": ev.event_type,
            "domain": ev.domain,
            "operation": ev.operation,
            "request_id": ev.request_id,
            "actor_ulid": ev.actor_ulid,
            "target_ulid": ev.target_ulid,
            "happened_at_utc": ev.happened_at_utc,
            "refs": json.loads(ev.refs_json) if ev.refs_json else None,
            "changed": json.loads(ev.changed_json) if ev.changed_json else None,
            "meta": json.loads(ev.meta_json) if ev.meta_json else None,
        }
        prev = prev_for.get(ev.chain_key)
        calc = _rehash(prev, env)
        assert calc == ev.curr_hash_hex, f"bad hash @ {ev.ulid}"
        prev_for[ev.chain_key] = ev.curr_hash_hex

def test_payload_has_no_pii_keys(_emit_some_events):
    """
    Ledger must remain PII-free: only names/codes/ids in JSON keys.
    We assert on keys, not values, to avoid chasing content.
    """
    deny = {"name_first","name_last","email","phone","street1","street2","ssn","dob"}
    rows = db.session.query(LedgerEvent).all()
    for ev in rows:
        for field in (ev.refs_json, ev.changed_json, ev.meta_json):
            if not field:
                continue
            data = json.loads(field)
            if isinstance(data, dict):
                keys = {str(k).lower() for k in data.keys()}
                assert not (keys & deny), f"PII-ish keys {keys & deny} in {ev.ulid}"
