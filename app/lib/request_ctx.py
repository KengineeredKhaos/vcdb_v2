# app/lib/request_ctx.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

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
