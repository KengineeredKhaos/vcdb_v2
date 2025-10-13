# Generated scaffolding — VCDB v2 — 2025-09-22 00:11:24 UTC
from __future__ import annotations

from typing import Any, Dict, Optional

from app.extensions import current_actor_id, enforcers, event_bus, ulid

"""Calendar services — business logic lives here.
Routes call into these functions; services emit events via app/extensions.event_bus.
"""


def example_noop(
    *, request_id: str, actor_id: Optional[str]
) -> Dict[str, Any]:
    """Example callable to prove wiring; replace with real logic."""
    return {"ok": True, "request_id": request_id, "actor_id": actor_id}


def create_special_event(*, budget_cents: int, request_id: str):
    enforcers.spend_cap(
        budget_cents,
        actor_id=current_actor_id(),
        request_id=request_id,
        extra={"context": "calendar.special_event"},
    )
    eid = ulid()
    # ...write event row...
    event_bus.emit(
        type="calendar.special_event.created",
        slice="calendar",
        operation="created",
        actor_id=current_actor_id(),
        request_id=request_id,
        target_id=eid,
    )
    return eid
