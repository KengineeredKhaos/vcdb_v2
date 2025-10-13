# app/slices/auth/decorators.py
from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def identity(view):
    """A no-op decorator that preserves the wrapped function’s identity."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        return view(*args, **kwargs)

    return wrapper


def roles_required(*required):
    """
    Gate a view to users having ANY of the required roles.
    Usage:
        @bp.get("/secret")
        @login_required
        @roles_required("admin", "staff")
        def secret(): ...
    """
    need = {r.strip().lower() for r in required if r}

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            # current_user.roles may be a set[str] (HeaderUser) or
            # relationship on ORM User
            user_roles = set()

            if hasattr(current_user, "roles"):
                # ORM model: roles is a relationship of Role objects
                # HeaderUser: roles is a set of strings
                roles_attr = current_user.roles
                if isinstance(roles_attr, (set, frozenset)):
                    user_roles = {r.lower() for r in roles_attr}
                else:
                    # assume iterable of objects with .name
                    try:
                        user_roles = {r.name.lower() for r in roles_attr}
                    except Exception:
                        user_roles = set()

            if not user_roles:
                abort(403)

            if need and user_roles.isdisjoint(need):
                abort(403)

            return view(*args, **kwargs)

        return wrapper

    return decorator
