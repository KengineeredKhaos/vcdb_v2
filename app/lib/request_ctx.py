# app/lib/request_ctx.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

"""
Lightweight request context (request_id and actor ULID).

This module uses contextvars to track per-request metadata without
requiring Flask's request globals:

- ensure_request_id() / get_request_id() / set_request_id(): manage the
  current request ULID (used for tracing and logs).
- get_actor_ulid() / set_actor_ulid(): track the current actor's entity
  ULID, if known.
- use_request_ctx(): context manager to temporarily set both values.
- as_dict(): convenience snapshot for logging/ledger emits.

Log messages and ledger events should pull context from here so we can
correlate actions across layers. Do not stash request-specific data in
global variables—use this module instead.
"""


from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from .ids import new_ulid

_request_id: ContextVar[str] = ContextVar("_request_id", default="")
_actor_ulid: ContextVar[Optional[str]] = ContextVar(
    "_actor_ulid", default=None
)


def ensure_request_id() -> str:
    rid = _request_id.get()
    if not rid:
        rid = new_ulid()
        _request_id.set(rid)
    return rid


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def get_request_id() -> str:
    return _request_id.get()


def set_actor_ulid(entity_ulid: Optional[str]) -> None:
    _actor_ulid.set(entity_ulid)


def get_actor_ulid() -> Optional[str]:
    return _actor_ulid.get()


def reset_request_ctx() -> None:
    _request_id.set("")
    _actor_ulid.set(None)


@contextmanager
def use_request_ctx(request_id: str, actor_ulid: Optional[str] = None):
    """Temporarily set request/actor context and restore on exit."""
    prev_rid = _request_id.get()
    prev_actor = _actor_ulid.get()
    try:
        set_request_id(request_id)
        if actor_ulid is not None:
            set_actor_ulid(actor_ulid)
        yield
    finally:
        _request_id.set(prev_rid)
        _actor_ulid.set(prev_actor)


def as_dict() -> dict:
    """Structured snapshot for logs/ledger emits."""
    return {"request_id": get_request_id(), "actor_ulid": get_actor_ulid()}


__all__ = [
    "ensure_request_id",
    "get_request_id",
    "set_request_id",
    "reset_request_ctx",
    "get_actor_ulid",
    "set_actor_ulid",
    "use_request_ctx",
    "as_dict",
]
