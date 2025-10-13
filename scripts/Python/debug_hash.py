# scripts/debug_hash.py
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.slices.transactions.services import compute_event_hash

app = create_app("config.DevConfig")
with app.app_context():
    rid = "01K626WEHV18FS309MX953DTZ6"
    row = (
        db.session.execute(
            text(
                """SELECT id, happened_at_utc, prev_event_id, prev_hash, event_hash,
                       type, slice, operation, request_id, actor_id, target_id,
                       entity_ids_json, changed_fields_json, refs_json
                FROM transactions_ledger WHERE id = :rid"""
            ),
            {"rid": rid},
        )
        .mappings()
        .one()
    )

    # Build the same payload your repair uses (prev_* already set on this row):
    payload = {
        "id": row["id"],
        "happened_at_utc": row["happened_at_utc"],
        "prev_event_id": row["prev_event_id"],
        "prev_hash": row["prev_hash"],
        "type": row["type"],
        "slice": row["slice"],
        "operation": row["operation"],
        "request_id": row["request_id"],
        "actor_id": row["actor_id"],
        "target_id": row["target_id"],
        "entity_ids_json": row["entity_ids_json"],
        "changed_fields_json": row["changed_fields_json"],
        "refs_json": row["refs_json"],
    }
    recalced = compute_event_hash(payload)
    print("stored:", row["event_hash"])
    print("recalc:", recalced)
