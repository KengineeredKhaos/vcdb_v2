# tests/foundation/test_event_bus_contract.py
def test_event_bus_emit_signature_does_not_drift(monkeypatch):
    from app.extensions import event_bus

    captured = {}

    def fake_emit(**kwargs):
        captured.update(kwargs)
        # assert required keys present
        for k in (
            "domain",
            "operation",
            "request_id",
            "actor_ulid",
            "target_ulid",
            "refs",
            "changed",
            "meta",
            "happened_at_utc",
            "chain_key",
        ):
            assert k in kwargs
        # assert forbidden keys not present
        assert "slice" not in kwargs
        assert "type" not in kwargs
        return {"ok": True}

    # Patch the downstream ledger emit so we only test surface
    import app.extensions.contracts.ledger.v2 as ledger_v2

    monkeypatch.setattr(ledger_v2, "emit", fake_emit)

    # Call the canon wrapper
    from app.lib.chrono import now_iso8601_ms
    from app.lib.ids import new_ulid

    event_bus.emit(
        domain="governance",
        operation="policy.updated",
        request_id=new_ulid(),
        actor_ulid="01ABCDEFGH...",
        target_ulid=None,
        refs={"k": "v"},
        changed=None,
        meta=None,
        happened_at_utc=now_iso8601_ms(),
    )

    assert captured["domain"] == "governance"
    assert captured["operation"] == "policy.updated"
