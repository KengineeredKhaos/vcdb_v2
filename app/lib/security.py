# app/lib/security.py
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable, Optional

audit = logging.getLogger("vcdb.audit")


def require_rbac(
    *roles: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator stub —
    validate the current user has at least one of the roles.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            # TODO: integrate with real auth (Flask-Login, etc.)
            # If not authorized, raise PermissionDenied from app.lib.errors
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def audit_action(event: str, **fields: Any) -> None:
    """Write a structured audit log line
    (caller sets request/actor ids in ctx)."""
    try:
        audit.info({"event": event, **fields})
    except Exception:
        # never blow up the request due to logging
        pass
