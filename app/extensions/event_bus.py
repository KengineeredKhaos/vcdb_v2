# app/extensions/event_bus.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <set to the relative path of this file>
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v2.0.0  (frozen)
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII in ledger


"""
# app/extensions/event_bus.py  (CANON — do not drift)
def emit(
    *,
    domain: str,                               # owning slice / domain
    operation: str,                            # what happened
    request_id: str,                           # request ULID
    actor_ulid: Optional[str],                 # who acted (ULID | None)
    target_ulid: Optional[str],                # primary subject | N/A
    refs: Optional[Dict[str, Any]] = None,     # small reference dictionary
    changed: Optional[Dict[str, Any]] = None,  # small “before/after” hints
    meta: Optional[Dict[str, Any]] = None,     # tiny extra context (PII-free)
    happened_at_utc: Optional[str] = None,     # ISO-8601 Z
    chain_key: Optional[str] = None,           # alternate chain (rare)
):
    return ledger_v2.emit( ... )  # exact forward, no renaming or extra fields

"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.extensions.contracts import ledger_v2

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "1.0.0"


def emit(
    *,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: Optional[str],
    target_ulid: Optional[str],
    refs: Optional[Dict[str, Any]] = None,
    changed: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    happened_at_utc: Optional[str] = None,
    chain_key: Optional[str] = None,
):
    # Keep the surface area small & stable
    return ledger_v2.emit(
        domain=domain,
        operation=operation,
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=target_ulid,
        refs=refs,
        changed=changed,
        meta=meta,
        happened_at_utc=happened_at_utc,
        chain_key=chain_key,
    )
