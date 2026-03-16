# app/slices/ledger/services.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <set to the relative path of this file>
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v1.0.0  (frozen)
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII in ledger
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import (  # use your finalized helpers
    dumps_compact,
    try_parse_json,
)

from .models import LedgerEvent

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "2.0.0"


def _json_safe(obj: Any) -> Any:
    """Recursively coerce to JSON-safe primitives."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, Mapping):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    # fallback: avoid exploding on classes/functions/SQLA models/etc.
    return str(obj)


def _canon_envelope(
    *,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: str | None,
    target_ulid: str | None,
    refs: dict[str, Any] | None,
    changed: dict[str, Any] | None,
    meta: dict[str, Any] | None,
    happened_at_utc: str | None = None,
    chain_key: str | None = None,
) -> dict[str, Any]:
    """Build a stable, minimal, string-serialized envelope for hashing."""
    event_type = f"{domain}.{operation}"
    ck = chain_key or domain
    env = {
        "chain_key": ck,
        "event_type": event_type,
        "domain": domain,
        "operation": operation,
        "request_id": request_id,
        "actor_ulid": actor_ulid,
        "target_ulid": target_ulid,
        "happened_at_utc": happened_at_utc or now_iso8601_ms(),
        "refs": refs or None,
        "changed": changed or None,
        "meta": meta or None,
    }
    return env


def _hash_env(prev_hash_hex: str | None, env: dict[str, Any]) -> str:
    """SHA-256 over prev-hash + compact JSON of envelope core fields."""
    h = hashlib.sha256()
    if prev_hash_hex:
        h.update(prev_hash_hex.encode("utf-8"))
    # hash only deterministic, compact representation
    h.update(dumps_compact(env).encode("utf-8"))
    return h.hexdigest()


def _digest(envelope: dict[str, Any]) -> bytes:
    # stable, ascii, sorted keys
    s = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(s.encode("utf-8")).digest()


def append_event(
    *,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: str | None,
    target_ulid: str | None,
    refs: dict[str, Any] | None = None,
    changed: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    happened_at_utc: str | None = None,
    chain_key: str | None = None,
) -> LedgerEvent:
    """
    Append a ledger event. Callers are slice services or the event bus.
    No PII—ULIDs and names only. This unit only flushes; caller commits.
    """
    env = _canon_envelope(
        domain=domain,
        operation=operation,  # always snake_case
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=target_ulid,
        refs=refs,
        changed=changed,
        meta=meta,
        happened_at_utc=happened_at_utc,
        chain_key=chain_key,
    )

    # Find previous hash for this chain
    stmt = (
        select(LedgerEvent.curr_hash_hex)
        .where(LedgerEvent.chain_key == env["chain_key"])
        .order_by(desc(LedgerEvent.ulid))
        .limit(1)
    )
    prev_hash_hex = db.session.execute(stmt).scalar_one_or_none()
    curr_hash_hex = _hash_env(prev_hash_hex, env)

    row = LedgerEvent(
        ulid=new_ulid(),
        chain_key=env["chain_key"],
        domain=env["domain"],
        operation=env["operation"],
        event_type=env["event_type"],
        actor_ulid=env["actor_ulid"],
        target_ulid=env["target_ulid"],
        request_id=env["request_id"],
        happened_at_utc=env["happened_at_utc"],
        refs_json=dumps_compact(env["refs"])
        if env["refs"] is not None
        else None,
        changed_json=dumps_compact(env["changed"])
        if env["changed"] is not None
        else None,
        meta_json=dumps_compact(env["meta"])
        if env["meta"] is not None
        else None,
        prev_hash_hex=prev_hash_hex,
        curr_hash_hex=curr_hash_hex,
        created_at_utc=now_iso8601_ms(),
    )
    db.session.add(row)
    db.session.flush()
    # ensure row is INSERTed so subsequent append_event()
    # calls in same txn see it
    return row


def verify_chain(chain_key: str | None = None) -> dict[str, Any]:
    """
    Recompute hashes for one chain or all chains and report the first break (if any).
    """

    def _iter_events(key: str | None) -> Iterable[LedgerEvent]:
        q = select(LedgerEvent).order_by(
            LedgerEvent.chain_key, LedgerEvent.ulid
        )
        if key:
            q = (
                select(LedgerEvent)
                .where(LedgerEvent.chain_key == key)
                .order_by(LedgerEvent.ulid)
            )
        return (x[0] for x in db.session.execute(q).all())

    broken = None
    checked = 0
    chains = set()

    prev_for: dict[str, str | None] = {}
    for ev in _iter_events(chain_key):
        chains.add(ev.chain_key)
        prev = prev_for.get(ev.chain_key)
        # reconstruct envelope as hashed
        env = {
            "chain_key": ev.chain_key,
            "event_type": ev.event_type,
            "domain": ev.domain,
            "operation": ev.operation,
            "request_id": ev.request_id,
            "actor_ulid": ev.actor_ulid,
            "target_ulid": ev.target_ulid,
            "happened_at_utc": ev.happened_at_utc,
            "refs": try_parse_json(ev.refs_json),
            "changed": try_parse_json(ev.changed_json),
            "meta": try_parse_json(ev.meta_json),
        }
        calc = _hash_env(prev, env)
        if calc != ev.curr_hash_hex:
            broken = {
                "chain_key": ev.chain_key,
                "event_id": ev.ulid,
                "expected": ev.curr_hash_hex,
                "recomputed": calc,
            }
            break
        prev_for[ev.chain_key] = ev.curr_hash_hex
        checked += 1

    return {
        "ok": broken is None,
        "checked": checked,
        "broken": broken,
        "chains": sorted(chains),
    }
