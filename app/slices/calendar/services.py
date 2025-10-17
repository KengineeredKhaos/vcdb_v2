# app/slices/calendar/services.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import current_actor_id, db, enforcers, event_bus, ulid
from app.extensions.contracts.finance import v1 as finance
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
    from app.slices.finance.models import Fund

    # not actually used in code paths


def _resolve_fund_summary(
    fund_ulid: Optional[str],
) -> Optional[dict[str, Any]]:
    if not fund_ulid:
        return None
    resp = finance.fund_get(
        {"request_id": f"cal-{fund_ulid}", "data": {"fund_ulid": fund_ulid}}
    )
    return resp["data"] if resp.get("ok") else None


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
