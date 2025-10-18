# tests/ledger/test_chain.py
def test_ledger_append_and_verify(app):
    from app.lib.chrono import now_iso8601_ms
    from app.slices.ledger import services as ledger

    # append one event
    ulid = ledger.log_event(
        "auth.login.success",
        happened_at=now_iso8601_ms(),
        actor_ulid="01ACTOR",
        subject_ulid="01USER",
        # all remaining fields are optional and default to None
    )
    assert isinstance(ulid, str) and len(ulid) == 26

    # verify the chain is intact
    result = ledger.verify_chain()
    assert result["ok"] is True
