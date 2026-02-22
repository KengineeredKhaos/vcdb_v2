# app/lib/guards.py
from __future__ import annotations

import re

"""
System-wide Helpers/Guards

Usage in a mutating service:

from app.lib.guards import (
    ensure_actor_ulid,
    ensure_entity_ulid,
    ensure_request_id,
)

ent = ensure_entity_ulid(entity_ulid)
rid = ensure_request_id(request_id)
act = ensure_actor_ulid(actor_ulid)
"""
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def ensure_entity_ulid(value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError("entity_ulid is required")
    if not _ULID_RE.match(v):
        raise ValueError("entity_ulid must be a ULID")
    return v


def ensure_actor_ulid(value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError("actor_ulid is required")
    if not _ULID_RE.match(v):
        raise ValueError("actor_ulid must be a ULID")
    return v


def ensure_request_id(value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError("request_id is required")
    # Keep it permissive: request_id may be ULID/UUID/etc.
    if len(v) > 128:
        raise ValueError("request_id is too long")
    return v
