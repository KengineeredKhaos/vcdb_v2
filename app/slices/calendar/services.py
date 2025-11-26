# app/slices/calendar/services.py
from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Optional, TypedDict

from app.extensions import db, event_bus
from app.extensions.contracts import finance_v2 as finance
from app.extensions.contracts.errors import ContractError
from app.extensions.policies import GOV_DATA, _load_and_cache
from app.lib.chrono import now_iso8601_ms

from .models import Project

"""Calendar services — business logic lives here.
Routes call into these functions;
services emit events via app/extensions.event_bus.
"""


class FundSummary(TypedDict, total=False):
    ulid: str
    code: str
    name: str
    restriction: str
    active: bool
    created_at_utc: str
    updated_at_utc: str


if TYPE_CHECKING:
    # type-only; won’t import at runtime
    pass

    # not actually used in code paths


def is_blackout(project_ulid: str, when_iso: str) -> bool:
    pol = _load_and_cache(
        GOV_DATA / "policy_calendar.json",
        "policy_calendar",
        "policy_calendar.schema.json",
    )
    # naive MVP: global blackout windows only
    windows = pol.get("global_blackouts", [])
    t = when_iso[:10]  # YYYY-MM-DD
    return any(w["start"] <= t <= w["end"] for w in windows)


def _resolve_fund_summary(
    fund_ulid: Optional[str],
) -> Optional[dict[str, Any]]:
    if not fund_ulid:
        return None
    try:
        dto = finance.get_fund_summary(fund_ulid)
    except ContractError:
        return None  # or re-raise if you want strict behavior
    return asdict(dto)


def create_project(data: dict, actor_ulid: str) -> dict:
    p = Project(
        project_title=data.get("project_title") or "untitled",
        fund_ulid=data.get("fund_ulid"),
        owner_ulid=data.get("owner_ulid"),
        phase_code=data.get("phase_code"),
        status=data.get("status") or "planned",
    )

    # Optional strict check: ensure fund exists
    if p.fund_ulid and not _resolve_fund_summary(p.fund_ulid):
        raise ValueError("Unknown fund_ulid")

    db.session.add(p)
    db.session.commit()

    event_bus.emit(
        "project.created",
        {
            "project_ulid": p.ulid,
            "fund_ulid": p.fund_ulid,
            "actor_ulid": actor_ulid,
            "happened_at": now_iso8601_ms(),
        },
    )

    return project_view(p.ulid)


def project_view(project_ulid: str) -> dict:
    p = db.session.get(Project, project_ulid)
    if not p:
        raise KeyError("project not found")
    return {
        "ulid": p.ulid,
        "title": p.project_title,
        "status": p.status,
        "phase_code": p.phase_code,
        "fund_ulid": p.fund_ulid,
        "fund": _resolve_fund_summary(p.fund_ulid),  # soft-resolved
        "owner_ulid": p.owner_ulid,
        "created_at_utc": p.created_at_utc,
        "updated_at_utc": p.updated_at_utc,
    }
