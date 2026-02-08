# app/extensions/auth_ctx.py

"""
Auth-layer adapter for the current actor ULID.

This module bridges Flask-Login's `current_user` to VCDB's notion of an
'actor' (the entity ULID we use in logs and ledger events).

For now, we keep things deliberately simple:
- If there is no authenticated user, we return None.
- If there IS an authenticated user, we mint and cache a ULID in the
  Flask session keyed by that user id.

In production you may instead:
- Store the actor's entity ULID on the User row, or
- Map RBAC users to Entity rows via Governance policy.

Either way, callers should treat `current_actor_ulid()` as the single
source of truth for "who is acting" at the Extensions layer and use it
to seed `request_ctx.set_actor_ulid()` and ledger emissions.
"""

from __future__ import annotations

from flask import session
from flask_login import current_user

from app.lib.ids import new_ulid

# -----------------------------------------
# Auth context shim: current_actor_ulid (ULID)
# -----------------------------------------


def current_actor_ulid() -> str | None:
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


def get_user_roles(user_ulid: str) -> list[str]:
    # Temporary bridge: call Auth slice today (later: Auth contract).
    from app.slices.auth import (
        services as auth_ro,
    )  # local import keeps boundary tight

    return list(auth_ro.get_user_roles(user_ulid))
