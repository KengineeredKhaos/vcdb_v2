# app/slices/auth/__init__.py

from __future__ import annotations

from flask import current_app, redirect, request, session, url_for
from flask_login import current_user, login_user
from flask_login.utils import login_required

from app.extensions import login_manager
from app.lib.ids import new_ulid

from .routes import bp

"""
VCDB v2 — Auth slice (__init__)

This module wires up the Auth blueprint, the Flask-Login integration, and
a lightweight SessionUser wrapper used in request contexts.

Auth session posture
====================

Auth audit / transaction deviation
==================================

The Auth slice intentionally deviates from the general project pattern for
Ledger writes.

- Auth services perform business mutation and may flush.
- Auth services do NOT emit Ledger events.
- Auth routes own all canonical ``event_bus.emit(...)`` calls.
- Auth routes also own ``db.session.commit()`` / rollback framing.

This keeps high-frequency session flows such as login failure and logout
success simple, readable, and durably auditable.

Requests carry a compact session identity object rather than an ORM model.
That payload is written at login time to ``session["session_user"]`` and
rebuilt into a SessionUser on later requests.

This keeps request auth lightweight while leaving the database as the
ground truth for account state and RBAC membership.

Dev-only helpers
================

Auto-login and impersonation remain development conveniences only. They
must never become part of the canonical production authentication path.

#------------------
# Security Sweep
# Tags & Examples
# -----------------

the format rule absolute for every touched route:

# VCDB-SEC: <STATUS> entry=<rbac> authority=<gate|none|pending> reason=<short_slug> test=<slug|none>

# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=none
# VCDB-SEC: STAGED entry=admin authority=pending reason=missing_admin_resolution test=admin_review_approve_permissions
# VCDB-SEC: OPEN entry=pending authority=pending reason=needs_matrix_decision test=customer_exception_permissions
# VCDB-SEC: PUBLIC entry=public authority=none reason=login_surface test=none

# VCDB-SEC: <STATUS> entry=<rbac> authority=<gate|none|pending> reason=<short_slug>

# Vocabulary:
#
# ACTIVE = Route reachable, working, and intentionally enforced
# STAGED = reachable, but still under development or review
# OPEN = concept/design exists, implementation incomplete
# PUBLIC = Route reachable and unrestricted
# UNTERMINATED = not actually wired through to a reachable working surface
#
#
# entry: RBAC Access Level requirements
# public
# authenticated_user
# admin
# staff
# auditor
# authenticated_user
# admin authority
#
# authority: RBAC or Domain Execution Authority requirments
# login_required
# admin-only
# adimin-dev-only
# governor-override
#
# reason: Special constraints/limitations/
# self_service_auth_surface
# admin_only_surface
#


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface
@bp.get("/customers/<ulid>")
@login_required
@require_rbac("staff", "admin")
def detail(...):

# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_review_path_incomplete
# @login_required
# @require_rbac("admin")
# @require_governance_authority("policy_override")
@bp.post("/admin/review/<ulid>/approve")
def approve(...):


# VCDB-SEC: OPEN entry=unknown authority=unknown reason=direct_vs_admin_mediated_unsettled
@bp.post("/customers/<ulid>/exception")
def exception(...):


# VCDB-SEC: PUBLIC entry=public authority=none reason=login_surface
@bp.get("/login")
def login(...):


For every STAGED or OPEN route, require a matching test note or test name slug
in the comment.

# VCDB-SEC: STAGED entry=admin authority=pending reason=missing_admin_resolution test=admin_review_approve_permissions

Use short slugs for reasons, such as:

missing_admin_resolution
awaiting_matrix_freeze
direct_vs_admin_mediated_unsettled
authority_rule_not_canonized
public_surface
operator_surface

For the actual sweep, use these grep checks:

rg "VCDB-SEC:" app/
rg "VCDB-SEC: STAGED" app/
rg "VCDB-SEC: OPEN" app/
rg "VCDB-SEC: PUBLIC" app/

"""


class SessionUser:
    def __init__(
        self,
        ulid: str,
        name: str,
        email: str | None,
        roles: list[str] | None,
        username: str | None = None,
        must_change_password: bool = False,
    ):
        clean_roles = sorted(
            {
                str(role).strip().lower()
                for role in (roles or [])
                if str(role).strip()
            }
        )

        self.ulid = ulid
        self.name = name
        self.username = username or name
        self.email = email or ""
        self.roles = clean_roles
        self.rbac_roles = clean_roles
        self.must_change_password = bool(must_change_password)

        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def get_id(self) -> str:
        return self.ulid


def session_identity_from_view(
    view: dict[str, object],
) -> dict[str, object]:
    username = str(view.get("username") or "user")
    return {
        "ulid": str(view["ulid"]),
        "name": username,
        "username": username,
        "email": str(view.get("email") or ""),
        "roles": list(view.get("roles") or []),
        "must_change_password": bool(view.get("must_change_password", False)),
    }


def _allow_dev_auto_login() -> bool:
    env_name = str(current_app.config.get("ENV", "")).lower()

    if env_name != "development":
        return False

    if current_app.config.get("AUTH_MODE") != "stub":
        return False

    if not current_app.config.get("ALLOW_DEV_STUB_AUTH", False):
        return False

    return bool(current_app.config.get("AUTO_LOGIN_ADMIN", False))


@login_manager.user_loader
def _load_user(user_ulid: str):
    ident = session.get("session_user")
    if ident and ident.get("ulid") == user_ulid:
        return SessionUser(**ident)
    return None


@bp.before_app_request
def _dev_auto_login():
    if not _allow_dev_auto_login():
        return

    if getattr(current_user, "is_authenticated", False):
        return

    identity = session.get("session_user")
    if not identity:
        roles = list(current_app.config.get("AUTO_LOGIN_ROLES", ["admin"]))
        identity = {
            "ulid": new_ulid(),
            "name": "dev",
            "username": "dev",
            "email": "",
            "roles": roles,
            "must_change_password": False,
        }
        session["session_user"] = identity

    try:
        login_user(SessionUser(**identity), remember=False)
    except Exception:
        pass


@bp.before_app_request
def _enforce_password_change():
    if not getattr(current_user, "is_authenticated", False):
        return

    if not bool(getattr(current_user, "must_change_password", False)):
        return

    allowed = {
        "auth.change_password_form",
        "auth.change_password_post",
        "auth.logout",
        "static",
    }
    if request.endpoint in allowed or request.endpoint is None:
        return
    return redirect(url_for("auth.change_password_form"))


@login_manager.request_loader
def _load_user_from_request(_req):
    ident = session.get("session_user")
    if ident:
        return SessionUser(
            ulid=ident.get("ulid"),
            name=ident.get("name") or ident.get("username") or "user",
            username=ident.get("username") or ident.get("name") or "user",
            email=ident.get("email") or "",
            roles=ident.get("roles") or [],
            must_change_password=bool(
                ident.get("must_change_password", False)
            ),
        )
    return None


__all__ = [
    "SessionUser",
    "bp",
    "session_identity_from_view",
]
