# app/slices/auth/decorators.py
from __future__ import annotations
from functools import wraps
from flask import abort
from flask_login import current_user, login_required


def roles_required(*need_codes: str):
    need = {c.strip().lower() for c in need_codes if c}

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            user_roles = set(getattr(current_user, "roles", []) or [])
            # current_user.roles can be list[str] or list[Role]; normalize:
            user_roles = {getattr(r, "code", r).lower() for r in user_roles}
            if need and user_roles.isdisjoint(need):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def rbac(*codes: str):
    return roles_required(*codes)
