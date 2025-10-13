#!/usr/bin/env python3
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from __future__ import annotations

import json
import os
import sqlite3
import sys

from app import create_app
from app.extensions import db

# import models so SQLAlchemy knows the schema to create
from app.slices.auth.models import Role, User, UserRole  # noqa
from app.slices.transactions.models import LedgerEvent  # noqa

try:
    pass  # noqa
except Exception:
    pass
try:
    pass  # noqa
except Exception:
    pass

APP = create_app("config.DevConfig")

# filename -> table name
MAP = {
    "users.json": "users",
    "roles.json": "roles",
    "user_roles.json": "user_roles",
    "governance_policy.json": "governance_policy",
    "governance_office.json": "governance_office",
    "party_person.json": "party_person",
    "party_contact.json": "party_contact",
    "parties.json": "parties",
    "transactions_ledger.json": "transactions_ledger",
}


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    cur = con.execute(f'PRAGMA table_info("{table}")')
    return [row[1] for row in cur.fetchall()]  # row[1] = column name


def rebuild_and_load(db_path: str, dumps_dir: Path):
    # 1) (Re)create schema from SQLAlchemy models
    with APP.app_context():
        # Drop & create to guarantee a clean slate
        db.drop_all()
        db.create_all()

    # 2) Bulk load JSON files, inserting only known columns
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys=OFF;")
        for fname, table in MAP.items():
            fpath = dumps_dir / fname
            if not fpath.exists():
                print(f"- skip {fname} (not found)")
                continue

            data = json.loads(fpath.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not data:
                print(f"- {fname}: 0 rows")
                continue

            cols_in_db = table_columns(con, table)
            # Only keep keys that actually exist in the table
            cols = [c for c in data[0].keys() if c in cols_in_db]
            if not cols:
                print(
                    f"- {fname}: no matching columns in table {table}, skipping"
                )
                continue

            placeholders = ",".join(["?"] * len(cols))
            sql = f'INSERT OR REPLACE INTO {table} ({",".join(cols)}) VALUES ({placeholders})'
            rows = [tuple(item.get(c) for c in cols) for item in data]
            con.executemany(sql, rows)
            print(
                f"- {fname}: inserted {len(rows)} → {table} (cols: {', '.join(cols)})"
            )

        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    db_uri = APP.config.get("SQLALCHEMY_DATABASE_URI", "")
    assert db_uri.startswith(
        "sqlite:///"
    ), "This helper expects SQLite in dev."
    db_path = db_uri.replace("sqlite:///", "")

    dumps_dir = Path("var/json-dumps")
    if not dumps_dir.exists():
        print(f"Create {dumps_dir} and copy your JSON dumps there.")
        sys.exit(2)

    # Danger: make sure the old/bad DB is gone before running
    for suffix in ("", "-wal", "-shm"):
        p = Path(db_path + suffix)
        if p.exists():
            p.unlink()

    rebuild_and_load(db_path, dumps_dir)
    print("Done.")
