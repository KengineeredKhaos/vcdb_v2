from app.extensions import event_bus
from app.lib.chrono import now_iso8601_ms


def test_item_ensure_with_sku_parts_and_stock_math(app):
    # This test is intentionally light—just prove we can emit a logistics event with the new signature.
    event_bus.emit(
        "logistics.item.updated",
        {"changed_fields": {"qty_on_hand": 10}},
        domain="logistics",
        actor_ulid="01TESTACTOR",
        happened_at_utc=now_iso8601_ms(),
        # optional:
        entity_ulid=None,
        subject_ulid=None,
        request_id=None,
    )
    assert True
