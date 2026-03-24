# app/slices/sponsors/services_calendar.py

from __future__ import annotations

from typing import Any

from app.extensions.contracts import calendar_v2, entity_v2

from . import services_crm as crm_svc
from .mapper import (
    SponsorCultivationOutcomeView,
    map_sponsor_cultivation_outcome,
)
from .services import get_profile_hints, set_profile_hints

CULTIVATION_PROJECT_TITLE = "Sponsor Cultivation"
CULTIVATION_TASK_KIND = "fundraising_cultivation"


def _display_name_for_sponsor(sponsor_entity_ulid: str) -> str:
    try:
        card = entity_v2.get_entity_name_card(sponsor_entity_ulid)
        return card.display_name or sponsor_entity_ulid
    except Exception:
        return sponsor_entity_ulid


def ensure_cultivation_project(
    *,
    actor_ulid: str,
    request_id: str,
):
    row = calendar_v2.find_project_by_title(
        project_title=CULTIVATION_PROJECT_TITLE
    )
    if row:
        return row

    return calendar_v2.create_project(
        project_title=CULTIVATION_PROJECT_TITLE,
        owner_ulid=actor_ulid,
        phase_code="active",
        status="planned",
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def create_cultivation_task(
    *,
    sponsor_entity_ulid: str,
    actor_ulid: str,
    request_id: str,
    funding_demand_ulid: str | None = None,
    assigned_to_ulid: str | None = None,
    due_at_utc: str | None = None,
):
    project = ensure_cultivation_project(
        actor_ulid=actor_ulid,
        request_id=request_id,
    )

    sponsor_name = _display_name_for_sponsor(sponsor_entity_ulid)
    assigned = assigned_to_ulid or actor_ulid

    task_title = f"Cultivate sponsor: {sponsor_name}"

    detail_lines = [
        "Schedule outreach / status update / information sharing session / lunch meeting / phone contact.",
        f"Sponsor: {sponsor_name} ({sponsor_entity_ulid})",
    ]

    requirements_json: dict[str, Any] = {
        "source_slice": "sponsors",
        "workflow": "cultivation",
        "sponsor_entity_ulid": sponsor_entity_ulid,
        "outcome": {
            "outcome_note": None,
            "follow_up_recommended": False,
            "off_cadence_follow_up_signal": False,
            "funding_interest_signal": False,
        },
    }

    if funding_demand_ulid:
        demand = calendar_v2.get_funding_demand(funding_demand_ulid)
        match = crm_svc.compute_opportunity_match(
            sponsor_entity_ulid=sponsor_entity_ulid,
            funding_demand_ulid=funding_demand_ulid,
        )

        detail_lines.append(
            f"Opportunity: {demand.title} ({funding_demand_ulid})"
        )
        detail_lines.append(f"Advisory fit: {match.fit_band}")
        detail_lines.append(
            f"Suggested next action: {match.suggested_next_action}"
        )

        requirements_json["funding_demand_ulid"] = funding_demand_ulid
        requirements_json["match"] = {
            "fit_band": match.fit_band,
            "positive_reasons": list(match.positive_reasons),
            "caution_reasons": list(match.caution_reasons),
            "manual_review_recommended": (match.manual_review_recommended),
            "suggested_next_action": match.suggested_next_action,
            "profile_note_hints": [
                {
                    "key": hint.key,
                    "label": hint.label,
                    "note": hint.note,
                }
                for hint in match.profile_note_hints
            ],
        }

    notes_txt = (
        "Capture outcome notes. "
        "If follow-up is needed, schedule the next cultivation touch."
    )

    return calendar_v2.create_task(
        project_ulid=project["ulid"],
        task_title=task_title,
        actor_ulid=actor_ulid,
        request_id=request_id,
        task_detail="\n".join(detail_lines),
        task_kind=CULTIVATION_TASK_KIND,
        hours_est_minutes=30,
        notes_txt=notes_txt,
        requirements_json=requirements_json,
        assigned_to_ulid=assigned,
        due_at_utc=due_at_utc,
    )


def list_recent_cultivation_outcomes(
    sponsor_entity_ulid: str,
    *,
    limit: int = 10,
) -> tuple[SponsorCultivationOutcomeView, ...]:
    rows = calendar_v2.list_cultivation_outcomes_for_sponsor(
        sponsor_entity_ulid=sponsor_entity_ulid,
        limit=limit,
    )
    return tuple(map_sponsor_cultivation_outcome(row) for row in rows)


def get_cultivation_outcome(
    task_ulid: str,
) -> SponsorCultivationOutcomeView | None:
    row = calendar_v2.get_cultivation_outcome(task_ulid=task_ulid)
    if row is None:
        return None
    return map_sponsor_cultivation_outcome(row)


def promote_cultivation_outcome_to_relationship_note(
    *,
    sponsor_entity_ulid: str,
    task_ulid: str,
    actor_ulid: str | None,
    request_id: str,
) -> str | None:
    outcome = get_cultivation_outcome(task_ulid)
    if outcome is None:
        raise ValueError("cultivation outcome not found")
    if outcome.sponsor_entity_ulid != sponsor_entity_ulid:
        raise ValueError("cultivation outcome does not belong to sponsor")

    note = str(outcome.outcome_note or "").strip()
    if not note:
        raise ValueError("cultivation outcome has no note to promote")

    current = get_profile_hints(sponsor_entity_ulid) or {}
    relationship_note = str(current.get("relationship_note") or "").strip()
    recognition_note = str(current.get("recognition_note") or "").strip()

    lines = [f"Cultivation outcome — {outcome.task_title}"]
    if outcome.done_at_utc:
        lines.append(f"Completed: {outcome.done_at_utc}")
    elif outcome.due_at_utc:
        lines.append(f"Due: {outcome.due_at_utc}")
    if outcome.funding_demand_ulid:
        lines.append(f"Demand: {outcome.funding_demand_ulid}")
    lines.append(note)

    promoted = "\n".join(lines).strip()

    if promoted and promoted in relationship_note:
        return None

    new_relationship_note = (
        f"{relationship_note}\n\n{promoted}".strip()
        if relationship_note
        else promoted
    )

    return set_profile_hints(
        sponsor_entity_ulid=sponsor_entity_ulid,
        payload={
            "relationship_note": new_relationship_note,
            "recognition_note": recognition_note,
        },
        actor_ulid=actor_ulid,
        request_id=request_id,
    )
