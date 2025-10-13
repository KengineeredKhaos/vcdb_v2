#!/usr/bin/env python3
"""
Repair the transactions_ledger link+hash chain for the most-recent N events.

- Seeds prev_* from the true predecessor just outside the window
- Walks oldest→newest inside the window
- Recomputes event_hash via app.slices.transactions.services.compute_event_hash
- Dry-run by default; use --commit to write updates
"""
from __future__ import annotations

import argparse
from typing import List, Tuple

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.slices.transactions.services import compute_event_hash

# Fields used to build the canonical hash payload
_HASH_KEYS = (
    "id",
    "happened_at_utc",
    "prev_event_id",
    "prev_hash",
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
)


def fetch_desc(limit: int):
    return (
        db.session.execute(
            text(
                f"""
        SELECT {",".join(_HASH_KEYS)}, event_hash
          FROM transactions_ledger
      ORDER BY happened_at_utc DESC, id DESC
         LIMIT :lim
    """
            ),
            {"lim": limit},
        )
        .mappings()
        .all()
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit",
        type=int,
        default=200,
        help="how many newest rows to repair",
    )
    ap.add_argument("--commit", action="store_true", help="apply updates")
    args = ap.parse_args()

    app = create_app("config.DevConfig")
    with app.app_context():
        # Fetch N+1 rows in DESC order (newest first)
        rows_desc = fetch_desc(args.limit + 1)
        if not rows_desc:
            print("No rows; nothing to do.")
            return

        # Seed from the true predecessor (the (N+1)th row), if it exists
        seed_prev_id = (
            rows_desc[args.limit]["id"]
            if len(rows_desc) > args.limit
            else None
        )
        seed_prev_hash = (
            rows_desc[args.limit]["event_hash"]
            if len(rows_desc) > args.limit
            else None
        )

        # Work on the N newest rows, oldest→newest
        window_rows = rows_desc[: args.limit][::-1]

        # For a quick banner
        head = rows_desc[0]["id"]
        tail = window_rows[0]["id"]
        print(
            f"LEDGER: head={head}  tail(window)={tail}  checked={len(window_rows)}"
        )

        updates: List[Tuple[str, str | None, str | None, str]] = []
        prev_id = seed_prev_id
        prev_hash = seed_prev_hash

        for row in window_rows:
            rid = row["id"]
            cur_prev_id = row.get("prev_event_id")
            cur_prev_hash = row.get("prev_hash")

            new_prev_id = prev_id
            new_prev_hash = prev_hash

            tmp = {k: row.get(k) for k in _HASH_KEYS}
            tmp["prev_event_id"] = new_prev_id
            tmp["prev_hash"] = new_prev_hash
            new_event_hash = compute_event_hash(tmp)

            if (
                (cur_prev_id != new_prev_id)
                or (cur_prev_hash != new_prev_hash)
                or (row.get("event_hash") != new_event_hash)
            ):
                updates.append(
                    (rid, new_prev_id, new_prev_hash, new_event_hash)
                )

            prev_id = rid
            prev_hash = new_event_hash

        if not updates:
            print("No changes needed; chain is consistent.")
            return

        print(f"Planned updates: {len(updates)}")
        for rid, npid, nph, neh in updates[:10]:
            print(
                f"  id={rid} prev_event_id={npid} prev_hash={nph} event_hash={neh}"
            )
        if len(updates) > 10:
            print(f"  ... and {len(updates)-10} more")

        if not args.commit:
            print("\nDry run only. Re-run with --commit to write changes.")
            return

        # Apply inside a single transaction
        with db.engine.begin() as conn:
            for rid, npid, nph, neh in updates:
                conn.execute(
                    text(
                        """
                        UPDATE transactions_ledger
                           SET prev_event_id=:pid,
                               prev_hash=:ph,
                               event_hash=:eh
                         WHERE id=:id
                    """
                    ),
                    {"pid": npid, "ph": nph, "eh": neh, "id": rid},
                )
        print(f"Applied {len(updates)} updates. Done.")


if __name__ == "__main__":
    main()
