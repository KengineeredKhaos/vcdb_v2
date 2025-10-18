def test_duplicate_event_rejected(app):
    from app.slices.ledger import services as ledger

    e = dict(
        type="auth.login.success",
        happened_at_utc="2024-01-01T00:00:00.000Z",
        actor_ulid="01A",
    )
    ledger.log_event(**e)
    with app.db.session.begin():
        with app.pytest.raises(Exception):
            ledger.log_event(**e)  # violates UNIQUE
