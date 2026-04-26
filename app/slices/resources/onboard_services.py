# app/slices/resources/onboard_services.py

"""
Resources onboarding wizard services.

Ethos:
- Routes are skinny; services do all writes.
- Services do NOT commit/rollback; routes own transactions.
- Flush before emitting ledger events.
- Wizard gathers draft data; Admin approves/activates later.

Wizard truth:
- Resource.onboard_step is the canonical resume pointer.
- "Step complete" means we wrote Resource.onboard_step (defaults OK).
"""

from __future__ import annotations

from typing import Any, Final

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import ensure_actor_ulid, ensure_request_id

from . import services as res_svc
from .models import Resource

STEPS: Final[tuple[str, ...]] = (
    "profile",
    "capabilities",
    "capacity",
    "pocs",
    "mou",
    "review",
    "complete",
)

STEP_LABELS: Final[dict[str, str]] = {
    "profile": "Profile",
    "capabilities": "Capabilities",
    "capacity": "Capacity",
    "pocs": "POCs",
    "mou": "MOU",
    "review": "Review",
    "complete": "Complete",
}

STEP_ENDPOINTS: Final[dict[str, str]] = {
    "profile": "resources.onboard_profile",
    "capabilities": "resources.onboard_capabilities",
    "capacity": "resources.onboard_capacity",
    "pocs": "resources.onboard_pocs",
    "mou": "resources.onboard_mou",
    "review": "resources.onboard_review",
    "complete": "resources.onboard_complete",
}


def step_index(step: str | None) -> int:
    if not step:
        return -1
    s = str(step).strip().lower()
    try:
        return STEPS.index(s)
    except ValueError:
        return -1


def step_label(step: str) -> str:
    return STEP_LABELS.get(step, step)


def ensure_resource_for_onboard(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    """Idempotent: create Resource facet row if missing."""
    return res_svc.ensure_resource(
        resource_entity_ulid=entity_ulid,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def wizard_next_step(*, entity_ulid: str) -> str:
    """Return the next wizard endpoint for this resource."""
    r = db.session.get(Resource, entity_ulid)
    if not r:
        return STEP_ENDPOINTS["profile"]

    idx = step_index(r.onboard_step)
    next_idx = idx + 1
    if next_idx < 0:
        next_idx = 0
    if next_idx >= len(STEPS):
        next_idx = len(STEPS) - 1

    return STEP_ENDPOINTS[STEPS[next_idx]]


def mark_step(
    *,
    entity_ulid: str,
    step: str,
    request_id: str,
    actor_ulid: str | None,
) -> bool:
    """
    Persist wizard progress and emit a small ledger event.

    Returns True if the step changed.
    """
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)

    step_key = str(step or "").strip().lower()
    if step_key not in STEPS:
        raise ValueError(f"invalid onboard step: {step!r}")

    r = db.session.get(Resource, entity_ulid)
    if not r:
        raise ValueError("resource not found")

    now = now_iso8601_ms()
    prev = (r.onboard_step or "").strip().lower() or None

    if prev == step_key:
        r.last_touch_utc = now
        db.session.flush()
        return False

    r.onboard_step = step_key
    r.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="resources",
        operation="onboard_step",
        actor_ulid=act,
        target_ulid=entity_ulid,
        request_id=rid,
        happened_at_utc=now,
        changed={"onboard_step": step_key, "prev": prev},
        meta={"origin": "onboard"},
    )
    return True


def review_snapshot(*, entity_ulid: str) -> dict[str, Any]:
    """Gather a PII-minimized snapshot for the review step."""

    view = res_svc.resource_view(entity_ulid)
    hints = res_svc.get_profile_hints(entity_ulid)
    pocs = res_svc.resource_list_pocs(resource_ulid=entity_ulid)

    return {
        "view": view,
        "profile_hints": hints,
        "pocs": pocs,
    }


def submit_onboard_admin_issue(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
):
    """
    Complete wizard progression and hand off to the Resources Admin issue flow.
    """
    from .admin_issue_services import raise_onboard_admin_issue

    mark_step(
        entity_ulid=entity_ulid,
        step="complete",
        request_id=request_id,
        actor_ulid=actor_ulid,
    )

    return raise_onboard_admin_issue(
        entity_ulid=entity_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )
