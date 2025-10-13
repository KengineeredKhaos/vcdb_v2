# app/slices/auth/user.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional, Set

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash


@dataclass
class User(UserMixin):
    id: int
    email: str
    username: str
    roles: Set[str] = field(default_factory=set)

    @staticmethod
    def _cx() -> sqlite3.Connection:
        cx = sqlite3.connect(current_app.config["DATABASE"])
        cx.row_factory = sqlite3.Row
        return cx

    @classmethod
    def authenticate(
        cls, login_value: str, password: str
    ) -> Optional["User"]:
        if not login_value or not password:
            current_app.logger.info(
                {"event": "auth_fail", "why": "missing_fields"}
            )
            return None

        cx = cls._cx()
        row = cx.execute(
            """
            SELECT id, email, COALESCE(username,'') AS username, password_hash
            FROM users
            WHERE email    = ? COLLATE NOCASE
               OR username = ? COLLATE NOCASE
            """,
            (login_value, login_value),
        ).fetchone()

        if not row:
            current_app.logger.info(
                {"event": "auth_fail", "why": "no_user", "login": login_value}
            )
            return None

        ok = False
        try:
            ok = check_password_hash(row["password_hash"], password)
        except Exception as e:
            current_app.logger.warning(
                {
                    "event": "auth_fail",
                    "why": "bad_hash_format",
                    "err": str(e),
                    "user_id": row["id"],
                }
            )
            return None

        if not ok:
            current_app.logger.warning(
                {
                    "event": "auth_fail",
                    "why": "bad_password",
                    "user_id": row["id"],
                }
            )
            return None

        roles_rows = cx.execute(
            """
            SELECT r.name
            FROM roles r
            JOIN user_roles ur ON ur.role_id = r.id
            WHERE ur.user_id = ?
            """,
            (row["id"],),
        ).fetchall()
        roles = {r["name"] for r in roles_rows}

        return cls(
            id=row["id"],
            email=row["email"],
            username=row["username"],
            roles=roles,
        )


def load_user(user_id: str) -> Optional[User]:
    cx = User._cx()
    row = cx.execute(
        "SELECT id, email, COALESCE(username,'') AS username FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    roles_rows = cx.execute(
        """
        SELECT r.name
        FROM roles r
        JOIN user_roles ur ON ur.role_id = r.id
        WHERE ur.user_id = ?
        """,
        (row["id"],),
    ).fetchall()
    roles = {r["name"] for r in roles_rows}
    return User(
        id=row["id"],
        email=row["email"],
        username=row["username"],
        roles=roles,
    )
