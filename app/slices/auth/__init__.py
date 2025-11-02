# app/slices/auth/__init__.py
from __future__ import annotations

from flask import Blueprint, current_app, request, session
from flask_login import current_user, login_user

from app.extensions import login_manager
from app.lib.ids import new_ulid

bp = Blueprint(
    "auth", __name__, url_prefix="/auth", template_folder="templates"
)

from . import models  # noqa: F401


class SessionUser:
    def __init__(
        self,
        ulid: str,
        name: str,
        email: str,
        roles: list[str],
        username: str | None = None,
    ):
        self.ulid = ulid
        self.name = name
        self.username = username or name
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
    from flask import current_app

    if not current_app.debug:
        return
    if getattr(current_user, "is_authenticated", False):
        return

    identity = session.get("session_user")
    if not identity:
        # pull default roles from config
        roles = list(current_app.config.get("AUTO_LOGIN_ROLES", ["admin"]))
        identity = {
            "ulid": new_ulid(),
            "name": "dev",
            "username": "dev",
            "email": "dev@example.org",
            "roles": roles,
        }
        session["session_user"] = identity

    try:
        login_user(SessionUser(**identity), remember=True)
    except Exception:
        pass


@bp.get("/dev/impersonate")
def dev_impersonate():
    """
    Usage examples (dev only):

    /auth/dev/impersonate?as=auditor

    /auth/dev/impersonate?roles=admin,auditor&next=/ledger

    This lets you test ledger:read as auditor without changing code.
    """

    from flask import current_app, redirect, request, url_for

    if not current_app.debug:
        return ("Not available", 404)

    # ?roles=admin,auditor  OR  ?as=auditor
    as_role = (request.args.get("as") or "").strip()
    roles_csv = (request.args.get("roles") or "").strip()
    if as_role and not roles_csv:
        roles_csv = as_role

    # sanitize vs configured stub role codes
    allowed = set(
        current_app.config.get("STUB_ROLE_CODES", {"user", "admin"})
    )
    roles = [
        r
        for r in (x.strip().lower() for x in roles_csv.split(","))
        if r in allowed
    ] or ["user"]

    ident = session.get("session_user") or {}
    ident.update({"roles": roles})
    session["session_user"] = ident

    # Re-login with new roles
    login_user(SessionUser(**ident), remember=True)

    return redirect(
        request.args.get("next")
        or current_app.config.get("DEV_START_URL", "/")
    )


@login_manager.request_loader
def _load_user_from_request(req: request):
    ident = session.get("session_user")
    if ident:
        # Accept session_user as an authenticated principal for this request.
        return SessionUser(
            ulid=ident.get("ulid"),
            name=ident.get("name") or ident.get("username") or "user",
            username=ident.get("username") or ident.get("name") or "user",
            email=ident.get("email") or "",
            roles=ident.get("roles") or [],
        )
    return None


__all__ = ["SessionUser", "bp"]
