# app/extensions/contracts/ledger/__init__.py

from typing import Any, Dict

from app.extensions.contracts.ledger import v2 as v2  # re-export module
from app.extensions.contracts.errors import (
    ContractConflict,
    ContractDataNotFound,
    ContractUnavailable,
)
from app.extensions.contracts.validate import load_schema, validate_payload
from app.slices.ledger import services as ledger


def emit_event(*, payload: Dict[str, Any]) -> Dict[str, Any]:
    req = load_schema(__file__, "schemas/event.request.json")
    validate_payload(payload, req)

    try:
        out = ledger.append_event(payload)  # provider-specific
    except ledger.EventHashConflict as e:
        # Map provider error to contract error
        # (don’t leak provider classes upward)
        raise ContractConflict(
            "Ledger hash conflict", details={"hint": "re-read tail"}, cause=e
        )
    except ledger.ProviderTemporarilyDown as e:
        raise ContractUnavailable("Ledger unavailable", cause=e)

    res = load_schema(__file__, "schemas/event.response.json")
    validate_payload(out, res)
    return out


def get_event(*, event_ulid: str) -> Dict[str, Any]:
    data = ledger.get_event(event_ulid)
    if not data:
        raise ContractDataNotFound(f"ledger event '{event_ulid}' not found")
    return data


__all__ = ["v2"]
