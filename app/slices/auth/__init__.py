# app/slices/auth/__init__.py
from __future__ import annotations

from flask import Blueprint, current_app, session

from app.extensions import login_manager
from app.lib.ids import new_ulid  # a stable ULID per DevOnly run


bp = Blueprint(
    "auth", __name__, url_prefix="/auth", template_folder="templates"
)


# @login_manager.user_loader
# def _load_user(user_id: str):
#     # Flask-Login passes a str; your DB query can accept it directly.
#     return load_user(user_id)

# -----------------
# User Loader (both stub and DB methods)
# -----------------


class SessionUser:  # minimal fallback so ruff stops complaining
    def __init__(self, user_id, name=None, email=None, roles=None):
        self.id = user_id
        self.name = name or "User"
        self.email = email
        self._roles = roles or []

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return self.id

    @property
    def roles(self):
        return list(self._roles)


@login_manager.user_loader
def _load_user(user_id: str):
    mode = (current_app.config.get("AUTH_MODE") or "stub").lower()
    if mode == "stub":
        data = session.get("users", {}).get(user_id)
        if not data:
            return None
        return SessionUser(
            user_id=user_id,
            name=data.get("name") or "User",
            email=data.get("email"),
            roles=data.get("roles") or [],
        )

    # DB-backed (implement when ready)
    try:
        from sqlalchemy import select

        from app.extensions import db

        # import your real User model once it exists
        from app.slices.auth.models import User  # TODO: create this model

        row = db.session.execute(
            select(User).where(User.ulid == user_id)
        ).scalar_one_or_none()
        if not row:
            return None
        return SessionUser(
            user_id=row.ulid,
            name=row.username or row.email,
            email=row.email,
            roles=[ur.role_code for ur in row.roles]
            if hasattr(row, "roles")
            else [],
        )
    except Exception:
        # Keep the app resilient if auth models aren't in place yet

        return None


@bp.before_app_request
def _dev_auto_login():
    """
    In dev + stub mode: if no user is logged in, auto-login a session admin.
    This does NOT run in test/prod.
    """
    try:
        if current_app.env != "development":
            return
        if (current_app.config.get("AUTH_MODE") or "stub").lower() != "stub":
            return
        if current_user.is_authenticated:
            return

        # Compose a dev identity (change to taste)
        user_ulid = session.get("dev_admin_ulid") or new_ulid()
        session["dev_admin_ulid"] = user_ulid
        identity = {
            "name": "Dev Admin",
            "email": "admin@example.local",
            "roles": ["admin"],
        }
        users = session.get("users", {})
        users[user_ulid] = identity
        session["users"] = users

        login_user(
            SessionUser(
                user_id=user_ulid,
                name=identity["name"],
                email=identity["email"],
                roles=identity["roles"],
            ),
            remember=True,
        )
    except Exception:
        # Never break requests if this convenience fails
        pass


from . import models, routes  # noqa: F401

__all__ = ["SessionUser"]
