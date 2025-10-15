from __future__ import annotations
from functools import wraps
from flask import abort
from flask_login import current_user


def roles_required(*need_codes: str):
    need = {c.strip().lower() for c in need_codes if c}

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            # 401: not logged in (no redirect during tests)
            if not getattr(current_user, "is_authenticated", False):
                abort(401)

            # Gather user roles as strings
            roles = getattr(current_user, "roles", []) or []
            user_roles = {getattr(r, "code", r).lower() for r in roles}

            # 403: logged in but lacks required roles
            if need and user_roles.isdisjoint(need):
                abort(403)

            return view(*args, **kwargs)

        return wrapper

    return decorator


def rbac(*codes: str):
    return roles_required(*codes)
