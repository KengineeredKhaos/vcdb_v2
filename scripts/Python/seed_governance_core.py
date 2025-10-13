#!/usr/bin/env python3
# scripts/seed_governance_core.py
# Generated 2025-09-22 03:46:35 UTC
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import sqlite3

DB_PATH = os.environ.get("VCDB_DB", "var/app-instance/dev.db")
SQL_PATH = os.environ.get("VCDB_SEED_SQL", "var/seeds/governance_core.sql")


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
    print("Seeded governance policies & offices into", DB_PATH)


if __name__ == "__main__":
    main()
