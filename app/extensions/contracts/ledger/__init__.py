# app/extensions/contracts/ledger/__init__.py

from __future__ import annotations

from typing import Any, Dict

from app.extensions.contracts import ledger_v2  # canon write-path
from app.extensions.errors import ContractError

# Re-export for legacy imports:
#   from app.extensions.contracts.ledger import v2
v2 = ledger_v2

__all__ = ["v2", "emit_event", "get_event"]


def emit_event(*, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    DEPRECATED v1-style JSON payload entrypoint.

    Kept only so old tests/CLI code that still call emit_event(payload=...)
    don't explode immediately. All new code should use event_bus.emit(...)
    (which calls ledger_v2.emit directly).

    Shape:
      payload = {
        "domain": str,
        "operation": str,
        "request_id": str,
        "actor_ulid": str | None,
        "target_ulid": str | None,
        "refs": dict | None,
        "changed": dict | None,
        "meta": dict | None,
        "happened_at_utc": str | None,
        "chain_key": str | None,
      }
    """
    where = "contracts.ledger.emit_event"

    required = ("domain", "operation", "request_id")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise ContractError(
            code="payload_invalid",
            where=where,
            message=f"missing required keys: {', '.join(missing)}",
            http_status=400,
            data={"missing": missing},
        )

    try:
        res = ledger_v2.emit(
            domain=payload["domain"],
            operation=payload["operation"],
            request_id=payload["request_id"],
            actor_ulid=payload.get("actor_ulid"),
            target_ulid=payload.get("target_ulid"),
            refs=payload.get("refs"),
            changed=payload.get("changed"),
            meta=payload.get("meta"),
            happened_at_utc=payload.get("happened_at_utc"),
            chain_key=payload.get("chain_key"),
        )
    except ContractError:
        # Already in canonical shape from ledger_v2.emit
        raise

    return {
        "ok": res.ok,
        "event_id": res.event_id,
        "event_type": res.event_type,
        "chain_key": res.chain_key,
    }


def get_event(*, event_ulid: str) -> Dict[str, Any]:
    """
    DEPRECATED helper for legacy callers that need to fetch a raw ledger row.

    New code should prefer slice-level read APIs instead of going directly
    through this contract.
    """
    from app.extensions import db
    from app.slices.ledger.models import LedgerEvent

    row = db.session.get(LedgerEvent, event_ulid)
    if not row:
        raise ContractError(
            code="not_found",
            where="contracts.ledger.get_event",
            message=f"ledger event '{event_ulid}' not found",
            http_status=404,
            data={"ulid": event_ulid},
        )

    return {
        "ulid": row.ulid,
        "chain_key": row.chain_key,
        "event_type": row.event_type,
        "domain": row.domain,
        "operation": row.operation,
        "actor_ulid": row.actor_ulid,
        "target_ulid": row.target_ulid,
        "request_id": row.request_id,
        "happened_at_utc": row.happened_at_utc,
        "refs_json": row.refs_json,
        "changed_json": row.changed_json,
        "meta_json": row.meta_json,
        "prev_hash_hex": row.prev_hash_hex,
        "curr_hash_hex": row.curr_hash_hex,
    }
