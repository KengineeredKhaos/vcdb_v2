#!/usr/bin/env python3
"""
Print recent ledger rows from transactions_ledger for quick sanity checks.

Usage:
  python scripts/print_ledger.py
  python scripts/print_ledger.py --type auth.user_role.assigned
  python scripts/print_ledger.py --slice governance
"""

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from app.slices.transactions.models import LedgerEvent, db

APP = create_app("config.DevConfig")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", dest="etype")
    parser.add_argument("--slice", dest="slice_")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    with APP.app_context():
        q = db.session.query(LedgerEvent)
        if args.etype:
            q = q.filter(LedgerEvent.type == args.etype)
        if args.slice_:
            q = q.filter(LedgerEvent.slice == args.slice_)
        q = q.order_by(LedgerEvent.happened_at_utc.desc()).limit(args.limit)
        rows = q.all()
        if not rows:
            print("(no rows)")
            return
        for r in rows:
            print(
                f"{r.happened_at_utc}  {r.type:<28} slice={r.slice:<12} actor={r.actor_id or '-':<26} "
                f"target={r.target_id or '-':<26} req={r.request_id}"
            )


if __name__ == "__main__":
    main()
