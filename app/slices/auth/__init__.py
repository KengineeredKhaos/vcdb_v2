# app/slices/auth/__init__.py

"""
VCDB v2 — Auth slice (__init__)

This module wires up the Auth blueprint, the Flask-Login integration, and
a lightweight SessionUser wrapper used in request contexts.

Responsibilities
================

* Register the ``auth`` Blueprint and attach login/logout routes and
  JSON admin helpers (see routes.py).
* Configure Flask-Login's user_loader so requests see a SessionUser that
  carries the ULID and RBAC roles for the current user.
* Provide **dev-only** helpers for auto-login and impersonation to make
  local development easier. These helpers are strictly disabled in
  production deployments.

SessionUser
===========

SessionUser is a small, non-ORM object used by Flask-Login. It keeps the
session cookie lean (user ULID + username + RBAC roles) and avoids
loading ORM models on every request. Ground truth for users and roles
lives in the Auth models and is exposed to other slices via contracts and
app/lib/security.py.

Dev-only helpers
================

During development, the module can:
    * auto-login a configured "dev" user on each request, and
    * allow an admin to impersonate another set of RBAC roles.

Both behaviors are gated by:
    * ``current_app.debug`` and
    * ``APP_MODE != "production"``.

In production:
    * auto-login never runs, and
    * the impersonation endpoint is effectively disabled.

These helpers exist purely for local/dev ergonomics and should be treated
as part of the devtools story, not as canonical auth behavior.
"""

from __future__ import annotations

from flask import Blueprint, current_app, request, session
from flask_login import current_user, login_user
from flask_login.utils import login_required

from app.extensions import login_manager
from app.lib.ids import new_ulid

bp = Blueprint(
    "auth", __name__, url_prefix="/auth", template_folder="templates"
)

from . import models


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


def _is_dev_mode() -> bool:
    """Return True only when it is safe to enable dev-only helpers.

    We require BOTH:
      - Flask debug mode (current_app.debug is True), and
      - APP_MODE is not "production" (defaulting to "dev" if missing).

    This ensures that auto-login / impersonate helpers can never be
    active in a production deployment, even if someone misconfigures
    Flask's DEBUG flag.
    """
    app_mode = current_app.config.get("APP_MODE", "dev")
    return bool(current_app.debug) and app_mode != "production"


@login_manager.user_loader
def _load_user(user_ulid: str):
    # SessionUser is enough for our needs (no DB read on every request)
    ident = session.get("session_user")
    if ident and ident.get("ulid") == user_ulid:
        return SessionUser(**ident)
    return None


@bp.before_app_request
def _dev_auto_login():
    """
    Dev-only auto login for a configured user.

    In dev mode, if no user is logged in, this will ensure a "dev"
    account exists and log it in automatically. This is a convenience
    for local development only and is disabled in production by
    `_is_dev_mode()`.
    """
    if not _is_dev_mode():
        return

    if getattr(current_user, "is_authenticated", False):
        return

    # existing logic: look up or create the dev user, then:
    #   login_user(SessionUser(...), remember=True)

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
@login_required
def dev_impersonate():
    """
    Dev-only endpoint to change the current SessionUser's RBAC roles.

    This is a debugging tool for exploring RBAC behavior locally.
    It is disabled in production by `_is_dev_mode()`.

    Usage examples (dev only):

    /auth/dev/impersonate?as=auditor

    /auth/dev/impersonate?roles=admin,auditor&next=/ledger

    This lets you test ledger:read as auditor without changing code.
    """

    from flask import redirect, request, url_for

    if not current_app.debug:
        # In production or non-debug modes, this endpoint should not exist.
        return ("Not available", 404)

    # existing impersonation logic:
    # - parse requested roles from query/form
    # - validate them against allowed dev roles list from config
    # - update SessionUser.roles
    # - maybe flash a message / redirect

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
