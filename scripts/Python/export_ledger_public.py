# scripts/export_ledger_public.py
#!/usr/bin/env python3
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import hashlib
import json
import os
import pathlib
from datetime import datetime, timezone

from app import create_app
from app.slices.transactions.models import LedgerEvent, db

APP = create_app("config.DevConfig")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


with APP.app_context():
    outdir = pathlib.Path("var/public-ledger")
    outdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data_path = outdir / f"ledger-{ts}.jsonl"
    with open(data_path, "w", encoding="utf-8") as f:
        q = db.session.query(LedgerEvent).order_by(
            LedgerEvent.happened_at_utc, LedgerEvent.id
        )
        for r in q.yield_per(500):
            rec = {
                "id": r.id,
                "request_id": r.request_id,
                "type": r.type,
                "slice": r.slice,
                "operation": r.operation,
                "happened_at_utc": r.happened_at_utc.isoformat(
                    timespec="seconds"
                ),
                "actor_id": r.actor_id,
                "target_id": r.target_id,
                "customer_id": r.customer_id,
                "changed_fields_json": r.changed_fields_json,
                "entity_ids_json": r.entity_ids_json,
                "refs_json": r.refs_json,
                "correlation_id": r.correlation_id,
                "reason": r.reason,
                "prev_event_id": r.prev_event_id,
                "prev_hash": r.prev_hash,
                "event_hash": r.event_hash,
                "watermark": {"exported_at": ts, "nonprofit": "VCDB v2"},
            }
            f.write(
                json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
                + "\n"
            )
    manifest = {
        "file": data_path.name,
        "sha256": sha256(data_path),
        "rows": db.session.query(LedgerEvent).count(),
        "generated_at": ts,
        "format": "jsonl",
        "schema": "transactions_ledger:v2",
    }
    with open(outdir / f"manifest-{ts}.json", "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)
    print("Wrote", data_path, "and manifest")
