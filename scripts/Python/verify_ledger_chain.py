# scripts/verify_ledger_chain.py
#!/usr/bin/env python3
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
from app.extensions import db
from app.slices.transactions.models import LedgerEvent
from app.slices.transactions.services import compute_event_hash

APP = create_app("config.DevConfig")

_HASH_KEYS = (
    "id",
    "type",
    "slice",
    "operation",
    "request_id",
    "actor_id",
    "target_id",
    "customer_id",
    "entity_ids_json",
    "changed_fields_json",
    "refs_json",
    "happened_at_utc",
    "prev_event_id",
    "prev_hash",
)


def canon(row):
    d = {k: getattr(row, k) for k in FIELDS}
    d["happened_at_utc"] = d["happened_at_utc"].isoformat(
        sep=" ", timespec="seconds"
    )
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode()


with APP.app_context():
    rows = (
        db.session.query(LedgerEvent)
        .order_by(LedgerEvent.happened_at_utc, LedgerEvent.id)
        .all()
    )

    prev_id = None
    prev_hash = None
    ok = True

    for r in rows:
        # Build the canonical payload just like the writer/repair do
        row_dict = {k: getattr(r, k) for k in _HASH_KEYS}
        row_dict["prev_event_id"] = prev_id
        row_dict["prev_hash"] = prev_hash

        expected_hash = compute_event_hash(row_dict)

        # 1) hash must match
        if r.event_hash != expected_hash:
            print(
                "HASH MISMATCH:",
                r.id,
                "stored=",
                r.event_hash,
                "expected=",
                expected_hash,
            )
            ok = False

        # 2) prev_event_id must point to the actual previous row
        if r.prev_event_id != prev_id:
            # first row is allowed to be None
            if prev_id is not None:
                print(
                    "LINK BREAK:",
                    r.id,
                    "prev_event_id=",
                    r.prev_event_id,
                    "expected=",
                    prev_id,
                )
                ok = False

        # 3) prev_hash must equal the previous row's event_hash
        if r.prev_hash != prev_hash:
            if prev_hash is not None:
                print(
                    "PREV_HASH MISMATCH:",
                    r.id,
                    "prev_hash=",
                    r.prev_hash,
                    "expected=",
                    prev_hash,
                )
                ok = False

        prev_id = r.id
        prev_hash = expected_hash

    print("OK" if ok else "FAIL")
    exit(0 if ok else 1)
