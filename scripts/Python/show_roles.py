#!/usr/bin/env python3
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import select

from app import create_app
from app.extensions import db

# adjust imports to your auth models
from app.slices.auth.models import Role, User, UserRole

APP = create_app("config.DevConfig")

"""
    Usage Notes:

    python scripts/show_roles.py 2

    will show the role for user #2

    user 2 roles: []
"""


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("user_id", type=int)
    args = p.parse_args()
    with APP.app_context():
        uid = db.session.execute(
            select(User.id).where(User.id == args.user_id)
        ).scalar()
        if not uid:
            print("user not found")
            return
        rows = (
            db.session.execute(
                select(Role.name)
                .join(UserRole, Role.id == UserRole.role_id)
                .where(UserRole.user_id == uid)
            )
            .scalars()
            .all()
        )
        print(f"user {args.user_id} roles:", rows or "[]")


if __name__ == "__main__":
    main()
