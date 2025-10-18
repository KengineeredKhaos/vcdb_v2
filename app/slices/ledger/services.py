# app/slices/ledger/services.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable, Mapping

from app.extensions import db

from .models import LedgerEvent


def verify_chain() -> dict:
    """
    Minimal integrity check for tests and the /ledger/verify route.
    Replace later with full prev_hash/chain_key validation as needed.
    """
    count = db.session.query(LedgerEvent).count()
    return {"ok": True, "count": count}


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


def _canonical_envelope(
    *,
    event_type: str,
    domain: str,
    operation: str,
    actor_ulid: str,
    happened_at_utc: str,
    request_id: str,
    subject_ulid: str | None,
    entity_ulid: str | None,
    changed_fields: dict | None,
    meta: dict | None,
) -> dict[str, Any]:
    # Only the fields that define event identity go into the digest:
    return {
        "event_type": event_type,
        "domain": domain,
        "operation": operation,
        "actor_ulid": actor_ulid,
        "happened_at_utc": happened_at_utc,
        "request_id": request_id,
        "subject_ulid": subject_ulid,
        "entity_ulid": entity_ulid,
        "changed_fields": _json_safe(changed_fields),
        "meta": _json_safe(meta),
    }


def _digest(envelope: dict[str, Any]) -> bytes:
    # stable, ascii, sorted keys
    s = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(s.encode("utf-8")).digest()


def log_event(
    *,
    event_type: str,
    domain: str,
    operation: str,
    actor_ulid: str,
    happened_at_utc: str,
    request_id: str,
    subject_ulid: str | None = None,
    entity_ulid: str | None = None,
    changed_fields: dict | None = None,
    meta: dict | None = None,
) -> None:
    # Build canonical, JSON-safe envelope first
    env = _canonical_envelope(
        event_type=event_type,
        domain=domain,
        operation=operation,
        actor_ulid=actor_ulid,
        happened_at_utc=happened_at_utc,
        request_id=request_id,
        subject_ulid=subject_ulid,
        entity_ulid=entity_ulid,
        changed_fields=changed_fields,
        meta=meta,
    )
    digest = _digest(env)

    row = LedgerEvent(
        # NOTE: event_type maps to column "type" in the model
        event_type=env["event_type"],
        domain=env["domain"],
        operation=env["operation"],
        actor_ulid=env["actor_ulid"],
        happened_at_utc=env["happened_at_utc"],
        request_id=env["request_id"],
        subject_ulid=env["subject_ulid"],
        entity_ulid=env["entity_ulid"],
        changed_fields=env["changed_fields"],  # JSON column, already safe
        meta=env["meta"],  # JSON column, already safe
        hash=digest,
        # TODO: fill chain_key / prev_hash here if you’re chaining
    )
    db.session.add(row)
