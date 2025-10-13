#!/usr/bin/env python3
from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import db
from app.slices.auth.models import User

APP = create_app("config.DevConfig")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--email", help="user email")
    p.add_argument("--id", type=int, help="user id")
    p.add_argument(
        "--password",
        help="plain password; if omitted, will prompt",
        default=None,
    )
    p.add_argument(
        "--force-change",
        action="store_true",
        help="require password change on next login",
    )
    args = p.parse_args()

    if not args.email and not args.id:
        p.error("provide --email or --id")

    with APP.app_context():
        q = User.query
        user = (
            q.filter_by(email=args.email).first()
            if args.email
            else q.get(args.id)
        )
        if not user:
            print("User not found")
            sys.exit(1)

        pw = args.password or getpass("New password: ")
        if not pw:
            print("Empty password not allowed")
            sys.exit(2)

        user.set_password(pw)
        if args.force_change:
            user.must_change_password = True

        db.session.commit()
        print(f"OK: set password for user id={user.id} email={user.email}")


if __name__ == "__main__":
    main()
