# app/lib/security.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL


from __future__ import annotations

from collections.abc import Iterable
from functools import wraps

from flask import abort, current_app, session
from flask_login import current_user

from app.extensions.auth_ctx import get_user_roles

ASSUME_KEY = "assumed_domain_roles"


def _dev_assumption_enabled(user) -> bool:
    if current_app.config.get("APP_MODE") == "production":
        return False
    has_dev = "dev" in getattr(user, "rbac_roles", [])
    # TODO: flip to real capability when Auth contract exposes it.
    # For now, use config toggle to allow/deny assumption in non-prod.
    allow = bool(current_app.config.get("ALLOW_DEV_ASSUME_ROLES", True))
    return has_dev and allow


def current_domain_roles(user) -> list[str]:
    base = set(getattr(user, "domain_roles", []))
    if _dev_assumption_enabled(user):
        assumed = set(session.get(ASSUME_KEY, []))
        return sorted(base | assumed)
    return sorted(base)


# -----------------
# Internal helpers
# -----------------


def _norm(codes: Iterable[str]) -> set[str]:
    return {str(c).strip().lower() for c in (codes or []) if c}


def _current_user_ulid() -> str | None:
    # SessionUser sets .ulid; real User model also has .ulid
    return getattr(current_user, "ulid", None)


def _current_user_roles() -> list[str]:
    """
    Prefer roles carried in the session object (fast).
    If not present or you want the ground truth,
    fall back to the Auth contract.
    """
    if getattr(current_user, "roles", None):
        return sorted(_norm(current_user.roles))
    uid = _current_user_ulid()
    if not uid:
        return []
    return sorted(_norm(get_user_roles(uid)))


def _is_authenticated() -> bool:
    return bool(getattr(current_user, "is_authenticated", False))


# -----------------
# Predicates
# (usable in services/CLI)
# -----------------


def user_has_any_roles(user_ulid: str, *need_codes: str) -> bool:
    have = set(get_user_roles(user_ulid))
    need = _norm(need_codes)
    return not have.isdisjoint(need) if need else True


def user_has_all_roles(user_ulid: str, *need_codes: str) -> bool:
    have = set(get_user_roles(user_ulid))
    need = _norm(need_codes)
    return need.issubset(have) if need else True


# -----------------
# Route Decorators
# (explicit where needed)
# -----------------
"""
How To Deploy RBAC & Domain role gates:

****   include in top level imports   ****
from app.lib.security import rbac, require_domain_roles_any

****   route predicate   ****
@rbac("admin")                           # RBAC gate
@require_domain_roles_any("governor")    # Domain-role gate (if required)
def <replace_with_route_nomenclature>():
    ...
Example above structured to respect Dev assertion of flexible Domain Roles
"""


def require_login():
    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_roles_any(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            have = set(_current_user_roles())
            if need and have.isdisjoint(need):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_roles_all(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            have = set(_current_user_roles())
            if need and not need.issubset(have):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_domain_roles_any(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            # Domain roles = DB roles (+ assumed roles if APP_MODE != production and user has 'dev')
            have = set(current_domain_roles(current_user))
            if need and have.isdisjoint(need):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_domain_roles_all(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            have = set(current_domain_roles(current_user))
            if need and not need.issubset(have):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_domain_role(code: str):
    """
    Convenience alias for the common case of gating on a single
    domain role, e.g., @require_domain_role("governor").
    """
    return require_domain_roles_any(code)


# convenience alias (to mirror rbac alias at bottom)
domain_roles_required = require_domain_roles_any


# -----------------
# Public helpers:
# role reading & convenience
# -----------------


def current_user_ulid() -> str | None:
    """Stable way for callers to get the current user's ULID (or None)."""
    return getattr(current_user, "ulid", None)


def current_user_roles() -> set[str]:
    """Ground-truth role set for the current user (lowercased)."""
    # Prefer session-carried roles if present; otherwise hit the Auth contract
    sess_roles = getattr(current_user, "roles", None)
    if sess_roles:
        return _norm(sess_roles)
    uid = current_user_ulid()
    if not uid:
        return set()
    return set(get_user_roles(uid))


def user_is_admin(user_ulid: str | None = None) -> bool:
    """Convenience for the common case."""
    uid = current_user_ulid() if user_ulid is None else user_ulid
    if not uid:
        return False
    return "admin" in set(get_user_roles(uid))


# -----------------
# Feature flag gate
# -----------------


def require_feature(flag_name: str):
    """
    Gate a route behind a simple app.config feature flag (truthy).
    Keeps unfinished admin pages tucked away without RBAC churn.
    """

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not bool(current_app.config.get(flag_name, False)):
                abort(404)
            return view(*args, **kwargs)

        return wrap

    return deco


# -----------------
# Optional: permission shim
# (role->permission mapping today, contract later)
# -----------------


def _permission_roles_map() -> dict[str, set[str]]:
    """
    Returns a mapping of permission -> roles that grant it.
    Today sourced from config PERMISSIONS_MAP; later can come from an Auth contract
    without changing call sites.
    Example config:
      PERMISSIONS_MAP = {
          "governance:policy:edit": {"admin"},
          "ledger:read": {"admin","auditor"},
      }
    """

    raw = current_app.config.get("PERMISSIONS_MAP", {}) or {}
    return {str(p).lower(): _norm(roles) for p, roles in raw.items()}


def user_has_permission(user_ulid: str, permission: str) -> bool:
    """Does this user have the given permission (via any mapped role)?"""
    need = str(permission).lower().strip()
    perm_map = _permission_roles_map()
    roles_for_perm = perm_map.get(need, set())
    if not roles_for_perm:
        return False
    have = set(get_user_roles(user_ulid))
    return not have.isdisjoint(roles_for_perm)


def require_permission(permission: str):
    """
    Route decorator that enforces a high-level permission.
    Internally maps permission -> roles (from config today).
    """
    need = str(permission).lower().strip()

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            uid = current_user_ulid()
            if not uid or not user_has_permission(uid, need):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


# -----------------
# compatibility aliases
# (so legacy imports keep working)
# -----------------

rbac = require_roles_any
roles_required = require_roles_any


__all__ = [
    "require_roles_any",
    "require_domain_roles_any",
    "require_domain_role",
    "rbac",
]
