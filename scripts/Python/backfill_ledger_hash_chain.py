#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json

# --- make 'app' importable no matter where you run the script from ---
import sys
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[1]
)  # repo root (folder that contains 'app/')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app import create_app
from app.slices.transactions.models import LedgerEvent, db

APP = create_app("config.DevConfig")

FIELDS = (
    "id",
    "request_id",
    "type",
    "slice",
    "operation",
    "happened_at_utc",
    "actor_id",
    "target_id",
    "customer_id",
    "changed_fields_json",
    "entity_ids_json",
    "refs_json",
    "correlation_id",
    "reason",
    "prev_event_id",
    "prev_hash",
)


def canon(row: LedgerEvent) -> bytes:
    d = {k: getattr(row, k) for k in FIELDS}
    if d["happened_at_utc"]:
        d["happened_at_utc"] = d["happened_at_utc"].isoformat(
            sep=" ", timespec="seconds"
        )
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


with APP.app_context():
    rows = (
        db.session.query(LedgerEvent)
        .order_by(LedgerEvent.happened_at_utc, LedgerEvent.id)
        .all()
    )

    prev_id, prev_hash = None, None
    for r in rows:
        r.prev_event_id = prev_id
        r.prev_hash = prev_hash
        r.event_hash = hashlib.sha256(canon(r)).hexdigest()
        prev_id, prev_hash = r.id, r.event_hash

    db.session.commit()
    print(f"Backfilled {len(rows)} ledger rows.")
