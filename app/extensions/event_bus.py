# app/extensions/event_bus.py
from __future__ import annotations

import warnings
from typing import Any, Callable, Dict, Optional

_handler = Optional[Callable[..., None]]


def subscribe(func: Callable[..., None]) -> None:
    """Attach a single sink (e.g., ledger.services.log_event)."""
    global _handler
    _handler = func


def unsubscribe() -> None:
    """Detach the sink."""
    global _handler
    _handler = None


_REQUIRED = (
    "event_type",
    "domain",
    "operation",
    "actor_ulid",
    "request_id",
)


# What field names will the event_bus accept
# define any acceptable elements from modules; normalize for the sink
def emit(
    *,
    event_type: str | None = None,
    domain: str,
    operation: str,
    actor_ulid: str,
    request_id: str,
    happened_at_utc: str | None = None,  # preferred
    subject_ulid: str | None = None,
    entity_ulid: str | None = None,
    changed_fields: Dict[str, Any] | None = None,
    meta: Dict[str, Any] | None = None,
) -> None:
    """Validate & forward to the subscribed sink."""
    if _handler is None:
        # No sink wired; nothing to do (intentionally silent in dev/tests).
        return

    # Minimal validation
    payload = locals()
    for k in _REQUIRED:
        if not payload[k]:
            raise ValueError(f"event_bus.emit missing required field: {k}")

    # Fan-out (single, normalized event sink for now)
    _handler(
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
