# app/extensions/auth_ctx.py

from __future__ import annotations

from typing import Optional

from flask import session
from flask_login import current_user

from app.lib.ids import new_ulid

# -----------------------------------------
# Auth context shim: current_actor_ulid (ULID)
# -----------------------------------------


def current_actor_ulid() -> Optional[str]:
    """
    Return a stable ULID for the *actor* in this session.
    In prod you might store an actor ULID on the user row;
    for dev we cache in session.
    """
    if not getattr(current_user, "is_authenticated", False):
        return None
    key = f"actor_ulid:u{getattr(current_user, 'id', 'anon')}"
    if key not in session:
        session[key] = new_ulid()
    return session[key]
