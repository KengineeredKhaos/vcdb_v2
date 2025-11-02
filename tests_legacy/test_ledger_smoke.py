# tests/test_ledger_smoke.py
from app.extensions.contracts.ledger import v2 as L
from app.lib.ids import new_ulid


def test_emit_and_verify(app):
    with app.app_context():
        r = L.emit(
            domain="smoke",
            operation="ping",
            request_id=new_ulid(),
            actor_ulid=None,
            target_ulid=None,
        )
        assert r.ok and r.event_id
        res = L.verify("smoke")
        assert res.get("ok")
        assert res.get("checked", 0) >= 1
