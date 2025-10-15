# app/slices/auth/__init__.py
from __future__ import annotations
from flask import Blueprint, current_app, session
from flask_login import current_user, login_user
from app.extensions import login_manager
from app.lib.ids import new_ulid

bp = Blueprint(
    "auth", __name__, url_prefix="/auth", template_folder="templates"
)


class SessionUser:
    def __init__(self, ulid: str, name: str, email: str, roles: list[str]):
        self.ulid = ulid
        self.name = name
        self.email = email
        self.roles = roles
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self) -> str:
        return self.ulid


@login_manager.user_loader
def _load_user(user_ulid: str):
    # SessionUser is enough for our needs (no DB read on every request)
    ident = session.get("session_user")
    if ident and ident.get("ulid") == user_ulid:
        return SessionUser(**ident)
    return None


@bp.before_app_request
def _dev_auto_login():
    if not current_app.debug:
        return
    if getattr(current_user, "is_authenticated", False):
        return
    identity = session.get("session_user")
    if not identity:
        identity = {
            "ulid": new_ulid(),
            "name": "dev",
            "email": "dev@example.org",
            "roles": ["admin"],  # convenient for local dev
        }
        session["session_user"] = identity
    try:
        login_user(SessionUser(**identity), remember=True)
    except Exception:
        pass


from . import models, routes  # noqa: F401

__all__ = ["SessionUser"]
