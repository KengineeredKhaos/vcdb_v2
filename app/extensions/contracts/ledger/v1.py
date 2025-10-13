# extensions/contracts/ledger/v1.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, NotRequired, TypedDict, cast

from app.extensions.contracts.types import (
    ContractRequest,
    ContractResponse,
)
from app.lib import new_ulid
from app.lib.chrono import parse_iso8601, to_iso8601, utc_now
from app.lib.ids import new_ulid  # central ULID helper

ALLOWED_DOMAINS = {
    "admin",
    "auth",
    "calendar",
    "customer",
    "entity",
    "governance",
    "finance",
    "sponsor",
    "logistics",
    "resource",
}


class LedgerEmitRequest(TypedDict, total=False):
    id: NotRequired[str]
    type: str
    domain: str
    operation: str
    happened_at_utc: NotRequired[str]
    request_id: str
    actor_id: NotRequired[str]
    target_id: NotRequired[str]
    changed_fields_json: NotRequired[dict]
    refs_json: NotRequired[dict]
    correlation_id: NotRequired[str]
    prev_event_id: NotRequired[str]
    prev_hash: NotRequired[str]


def _hash(event: dict) -> str:
    # Exclude event_hash itself to compute the hash
    e = {k: v for k, v in event.items() if k != "event_hash"}
    payload = json.dumps(
        e, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def emit(req: ContractRequest) -> ContractResponse:
    data = cast(LedgerEmitRequest, req["data"])
    missing = [
        k
        for k in ("type", "domain", "operation", "request_id")
        if k not in data
    ]
    if missing:
        return {
            "contract": "ledger.emit.v1",
            "request_id": req["request_id"],
            "ts": utc_now(),
            "ok": False,
            "errors": [
                {
                    "code": "BAD_REQUEST",
                    "message": f"Missing fields: {missing}",
                }
            ],
        }
    if data["domain"] not in ALLOWED_DOMAINS:
        return {
            "contract": "ledger.emit.v1",
            "request_id": req["request_id"],
            "ts": utc_now(),
            "ok": False,
            "errors": [
                {
                    "code": "BAD_REQUEST",
                    "field": "domain",
                    "message": f"Unknown domain '{data['domain']}'",
                }
            ],
        }

    event = {
        "id": data.get("id") or new_ulid(),
        "type": data["type"],
        "domain": data["domain"],
        "operation": data["operation"],
        "happened_at_utc": data.get("happened_at_utc") or utc_now(),
        "request_id": data["request_id"],
        "actor_id": data.get("actor_id"),
        "target_id": data.get("target_id"),
        "changed_fields_json": data.get("changed_fields_json") or {},
        "refs_json": data.get("refs_json") or {},
        "correlation_id": data.get("correlation_id"),
        "prev_event_id": data.get("prev_event_id"),
        "prev_hash": data.get("prev_hash"),
    }
    event["event_hash"] = _hash(event)

    if req.get("dry_run", False):
        return {
            "contract": "ledger.emit.v1",
            "request_id": req["request_id"],
            "ts": utc_now(),
            "ok": True,
            "data": {
                "id": event["id"],
                "event_hash": event["event_hash"],
                "preview": True,  # or False in the non-dry-run path
            },
        }

    if not req.get("dry_run", False):
        # Persist via Ledger slice service (append-only)
        from app.slices.ledger import services as ledger_svc

        # Expect this to either return (event_id, event_hash)
        # or the saved event
        saved = ledger_svc.append_event(event)  # adjust it to API
        # optionally overwrite with authoritative values from DB/service:
        event["id"] = saved.get("id", event["id"])
        event["event_hash"] = saved.get("event_hash", event["event_hash"])

        return {
            "contract": "ledger.emit.v1",
            "request_id": req["request_id"],
            "ts": utc_now(),
            "ok": True,
            "data": {
                "id": event["id"],
                "event_hash": event["event_hash"],
                "preview": False,
            },
        }


def emit_event(
    *,
    domain: str,
    operation: str,
    actor_id: str | None,
    target_id: str | None,
    happened_at: datetime,
    changed_fields: Mapping[str, Any] | None = None,
    refs: Mapping[str, Any] | None = None,
) -> str:
    """
    Convenience: builds a canonical event dict and
    calls the same slice function.
    Returns the new event ULID.
    """
    from app.slices.ledger import services as svc

    event = {
        "id": new_ulid(),
        "type": "event",  # or a more specific type from the caller
        "domain": domain,
        "operation": operation,
        "happened_at_utc": to_iso8601(happened_at),
        "request_id": new_ulid(),  # if none supplied by caller
        "actor_id": actor_id,
        "target_id": target_id,
        "changed_fields_json": changed_fields or {},
        "refs_json": refs or {},
    }
    event["event_hash"] = _hash(event)
    saved = ledger_svc.append_event(event)
    return saved.get("id", event["id"])
