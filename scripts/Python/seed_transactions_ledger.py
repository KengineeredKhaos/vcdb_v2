#!/usr/bin/env python3
# scripts/seed_transactions_ledger.py
# Generated 2025-09-22 03:15:18 UTC
import os
import sqlite3
import sys

DB_PATH = os.environ.get("VCDB_DB", "var/app-instance/dev.db")
SQL_PATH = os.environ.get(
    "VCDB_SEED_SQL", "var/seeds/transactions_ledger.sql"
)


def main():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(SQL_PATH):
        print(f"Seed SQL not found: {SQL_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(SQL_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(sql)
    print("Ensured transactions_ledger exists in", DB_PATH)


if __name__ == "__main__":
    main()
