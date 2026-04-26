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
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import (
    dumps_compact,
    try_parse_json,
)

from .errors import (
    EventHashConflict,
    LedgerBadArgument,
    LedgerUnavailable,
    ProviderTemporarilyDown,
)
from .models import LedgerEvent

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "2.0.0"


def _clean_required_str(
    label: str,
    value: str,
    *,
    max_len: int | None = None,
) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise LedgerBadArgument(f"{label} must be non-empty")
    if max_len is not None and len(clean) > max_len:
        raise LedgerBadArgument(f"{label} exceeds max length {max_len}")
    return clean


def _clean_optional_str(
    label: str,
    value: str | None,
    *,
    max_len: int | None = None,
) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    if max_len is not None and len(clean) > max_len:
        raise LedgerBadArgument(f"{label} exceeds max length {max_len}")
    return clean


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
    clean_domain = _clean_required_str("domain", domain, max_len=40)
    clean_operation = _clean_required_str(
        "operation",
        operation,
        max_len=60,
    )
    clean_request_id = _clean_required_str(
        "request_id",
        request_id,
        max_len=64,
    )
    clean_chain_key = (
        _clean_optional_str(
            "chain_key",
            chain_key,
            max_len=40,
        )
        or clean_domain
    )

    event_type = f"{clean_domain}.{clean_operation}"
    if len(event_type) > 120:
        raise LedgerBadArgument("event_type exceeds max length 120")

    env = {
        "chain_key": clean_chain_key,
        "event_type": event_type,
        "domain": clean_domain,
        "operation": clean_operation,
        "request_id": clean_request_id,
        "actor_ulid": _clean_optional_str(
            "actor_ulid",
            actor_ulid,
            max_len=64,
        ),
        "target_ulid": _clean_optional_str(
            "target_ulid",
            target_ulid,
            max_len=64,
        ),
        "happened_at_utc": happened_at_utc or now_iso8601_ms(),
        "refs": _json_safe(refs) if refs is not None else None,
        "changed": _json_safe(changed) if changed is not None else None,
        "meta": _json_safe(meta) if meta is not None else None,
    }
    return env


def _hash_env(prev_hash_hex: str | None, env: dict[str, Any]) -> str:
    """SHA-256 over prev-hash + compact JSON of envelope core fields."""
    h = hashlib.sha256()
    if prev_hash_hex:
        h.update(prev_hash_hex.encode("utf-8"))
    h.update(dumps_compact(env).encode("utf-8"))
    return h.hexdigest()


def _digest(envelope: dict[str, Any]) -> bytes:
    s = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(s.encode("utf-8")).digest()


def _event_to_env(ev: LedgerEvent) -> dict[str, Any]:
    """Rebuild the canonical event envelope from a stored row."""
    return {
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


def _extract_idempotency_key(env: dict[str, Any]) -> str | None:
    """
    Pull an explicit replay key from meta/refs.

    Ledger does not guess based only on request_id + event_type because one
    request may legitimately emit more than one event of the same type.
    """
    for bucket_name in ("meta", "refs"):
        bucket = env.get(bucket_name)
        if not isinstance(bucket, Mapping):
            continue
        for key_name in ("idempotency_key", "source_action_ulid"):
            value = bucket.get(key_name)
            clean = str(value or "").strip()
            if clean:
                return clean[:128]
    return None


def _logical_payload_hash(env: dict[str, Any]) -> str:
    """
    Hash the logical event payload for idempotent replay comparison.

    happened_at_utc is intentionally excluded. A replay attempt may happen at
    a different clock time while still representing the same logical write.
    """
    logical = dict(env)
    logical.pop("happened_at_utc", None)
    payload = json.dumps(
        logical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_idempotent_event(
    *,
    env: dict[str, Any],
    idempotency_key: str,
) -> LedgerEvent | None:
    """Find a prior event with the same explicit idempotency key."""
    stmt = (
        select(LedgerEvent)
        .where(
            LedgerEvent.chain_key == env["chain_key"],
            LedgerEvent.event_type == env["event_type"],
            LedgerEvent.request_id == env["request_id"],
        )
        .order_by(LedgerEvent.ulid)
    )
    if env.get("target_ulid"):
        stmt = stmt.where(LedgerEvent.target_ulid == env["target_ulid"])

    for row in db.session.execute(stmt).scalars():
        old_env = _event_to_env(row)
        if _extract_idempotency_key(old_env) == idempotency_key:
            return row
    return None


def _handle_idempotent_replay(env: dict[str, Any]) -> LedgerEvent | None:
    """
    Accept exact logical replays and reject conflicting replays.

    Return an existing event when the replay is safe. Return None when no
    prior matching idempotency key exists.
    """
    idempotency_key = _extract_idempotency_key(env)
    if not idempotency_key:
        return None

    existing = _find_idempotent_event(
        env=env,
        idempotency_key=idempotency_key,
    )
    if existing is None:
        return None

    attempted_hash = _logical_payload_hash(env)
    existing_hash = _logical_payload_hash(_event_to_env(existing))
    if attempted_hash == existing_hash:
        return existing

    raise EventHashConflict(
        "idempotency key replay conflicts with existing ledger event; "
        f"event_ulid={existing.ulid} chain_key={existing.chain_key}"
    )


def _is_transient_provider_error(exc: SQLAlchemyError) -> bool:
    """Best-effort classification for retryable provider conditions."""
    if isinstance(exc, OperationalError):
        return True
    text = str(exc).lower()
    transient_markers = (
        "database is locked",
        "database table is locked",
        "connection reset",
        "connection refused",
        "connection timed out",
        "server closed the connection",
        "temporarily unavailable",
        "timeout",
    )
    return any(marker in text for marker in transient_markers)


def _raise_provider_error(*, during: str, exc: SQLAlchemyError) -> None:
    message = f"ledger provider unavailable during {during}"
    if _is_transient_provider_error(exc):
        raise ProviderTemporarilyDown(message) from exc
    raise LedgerUnavailable(message) from exc


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

    try:
        replay = _handle_idempotent_replay(env)
        if replay is not None:
            return replay

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
        return row
    except (EventHashConflict, LedgerBadArgument):
        raise
    except SQLAlchemyError as exc:
        _raise_provider_error(during="append", exc=exc)


def verify_chain(chain_key: str | None = None) -> dict[str, Any]:
    """
    Recompute hashes for one chain or all chains and report the first
    break (if any).
    """
    clean_chain_key = _clean_optional_str(
        "chain_key",
        chain_key,
        max_len=40,
    )

    def _iter_events(key: str | None) -> Iterable[LedgerEvent]:
        q = select(LedgerEvent).order_by(
            LedgerEvent.chain_key,
            LedgerEvent.ulid,
        )
        if key:
            q = (
                select(LedgerEvent)
                .where(LedgerEvent.chain_key == key)
                .order_by(LedgerEvent.ulid)
            )
        return (x[0] for x in db.session.execute(q).all())

    try:
        broken = None
        checked = 0
        chains = set()

        prev_for: dict[str, str | None] = {}
        for ev in _iter_events(clean_chain_key):
            chains.add(ev.chain_key)
            prev = prev_for.get(ev.chain_key)
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
            if ev.prev_hash_hex != prev:
                broken = {
                    "chain_key": ev.chain_key,
                    "event_id": ev.ulid,
                    "kind": "prev_hash_mismatch",
                    "expected_prev": prev,
                    "observed_prev": ev.prev_hash_hex,
                }
                break

            calc = _hash_env(prev, env)
            if calc != ev.curr_hash_hex:
                broken = {
                    "chain_key": ev.chain_key,
                    "event_id": ev.ulid,
                    "kind": "curr_hash_mismatch",
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
    except LedgerBadArgument:
        raise
    except SQLAlchemyError as exc:
        _raise_provider_error(during="verify", exc=exc)
