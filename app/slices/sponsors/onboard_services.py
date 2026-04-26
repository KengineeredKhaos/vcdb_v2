# app/slices/sponsors/onboard_services.py

from __future__ import annotations

from typing import Any, Final

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import ensure_actor_ulid, ensure_request_id

from . import services as sp_svc
from .models import Sponsor

STEPS: Final[tuple[str, ...]] = (
    "profile",
    "pocs",
    "funding_rules",
    "mou",
    "review",
    "complete",
)

STEP_LABELS: Final[dict[str, str]] = {
    "profile": "Profile",
    "pocs": "POCs",
    "funding_rules": "Funding rules",
    "mou": "MOU",
    "review": "Review",
    "complete": "Complete",
}

STEP_ENDPOINTS: Final[dict[str, str]] = {
    "profile": "sponsors.onboard_profile",
    "pocs": "sponsors.onboard_pocs",
    "funding_rules": "sponsors.onboard_funding_rules",
    "mou": "sponsors.onboard_mou",
    "review": "sponsors.onboard_review",
    "complete": "sponsors.onboard_complete",
}


def step_index(step: str | None) -> int:
    if not step:
        return -1
    s = str(step).strip().lower()
    try:
        return STEPS.index(s)
    except ValueError:
        return -1


def ensure_sponsor_for_onboard(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    return sp_svc.ensure_sponsor(
        sponsor_entity_ulid=entity_ulid,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def wizard_next_step(*, entity_ulid: str) -> str:
    s = db.session.get(Sponsor, entity_ulid)
    if not s:
        return STEP_ENDPOINTS["profile"]

    idx = step_index(s.onboard_step)
    nxt = idx + 1
    if nxt < 0:
        nxt = 0
    if nxt >= len(STEPS):
        nxt = len(STEPS) - 1
    return STEP_ENDPOINTS[STEPS[nxt]]


def mark_step(
    *,
    entity_ulid: str,
    step: str,
    request_id: str,
    actor_ulid: str | None,
) -> bool:
    rid = ensure_request_id(request_id)
    actor = ensure_actor_ulid(actor_ulid)
    step_key = str(step or "").strip().lower()
    if step_key not in STEPS:
        raise ValueError(f"invalid onboard step: {step!r}")

    s = db.session.get(Sponsor, entity_ulid)
    if not s:
        raise ValueError("sponsor not found")

    now = now_iso8601_ms()
    prev = (s.onboard_step or "").strip().lower() or None
    if prev == step_key:
        s.last_touch_utc = now
        db.session.flush()
        return False

    s.onboard_step = step_key
    s.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="onboard_step",
        actor_ulid=actor,
        target_ulid=entity_ulid,
        request_id=rid,
        happened_at_utc=now,
        changed={"onboard_step": step_key, "prev": prev},
        meta={"origin": "onboard"},
    )
    return True


def submit_onboard_admin_issue(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
):
    """
    Complete wizard progression and hand off to the Sponsors Admin issue flow.
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


def review_snapshot(*, entity_ulid: str) -> dict[str, Any]:
    return {
        "view": sp_svc.sponsor_view(entity_ulid),
        "profile_hints": sp_svc.get_profile_hints(entity_ulid),
        "pocs": sp_svc.sponsor_list_pocs(sponsor_entity_ulid=entity_ulid),
        "restrictions": sp_svc.get_donation_restrictions(entity_ulid),
    }
