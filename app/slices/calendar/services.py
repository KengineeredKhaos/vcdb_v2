# app/slices/calendar/services.py
from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Dict, Optional, TypedDict

from app.extensions import db, event_bus
from app.extensions.contracts import finance_v2 as finance
from app.extensions.errors import ContractError
from app.extensions.policies import GOV_DATA, _load_and_cache
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

from .models import Project, ProjectFundingPlan

"""Calendar services — business logic lives here.
Projects, Tasks and Project Budgets orginate here as well.
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


# -----------------
# Project Context
# services related
# to planning,
# budget & funding
# -----------------

# -----------------
# Create Project
# -----------------


def create_project(
    data: dict, actor_ulid: str, request_id: str | None = None
) -> dict:
    """
    Create a Calendar Project and emit a domain event.

    Args:
        data:
            - project_title: str (required; falls back to "untitled")
            - fund_ulid: str | None
            - owner_ulid: str | None
            - phase_code: str | None
            - status: str | None (defaults to "planned")
        actor_ulid:
            Entity ULID of the actor creating this project.
        request_id:
            Optional correlation id (e.g. HTTP request id or ULID).
            If omitted, a new ULID will be generated for the event.

    Returns:
        dict: projection from project_view(p.ulid)
    """
    title = (data.get("project_title") or "untitled").strip()
    status = (data.get("status") or "planned").strip()

    p = Project(
        project_title=title,
        fund_ulid=data.get("fund_ulid"),
        owner_ulid=data.get("owner_ulid"),
        phase_code=data.get("phase_code"),
        status=status,
    )

    # Optional strict check: ensure fund exists (soft-fails as ValueError)
    if p.fund_ulid and not _resolve_fund_summary(p.fund_ulid):
        raise ValueError("Unknown fund_ulid")

    db.session.add(p)
    db.session.commit()

    # PII-free event: only ULIDs + status-ish fields
    event_bus.emit(
        domain="calendar",
        operation="project.created",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=p.ulid,
        changed={
            "status": p.status,
            "phase_code": p.phase_code,
        },
        refs={
            "fund_ulid": p.fund_ulid,
            "owner_ulid": p.owner_ulid,
        },
        happened_at_utc=p.created_at_utc,
    )

    return project_view(p.ulid)


# -----------------
# Funding Planning
# -----------------


def create_project_funding_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a ProjectFundingPlan row for a Calendar Project.

    This is the *planning-time* Lego: it records that a given Project is
    expected to receive funding from some source (grant, sponsor, internal)
    and, optionally, how much and into which fund archetype.

    Expected payload keys
    ---------------------

    Required:
      - project_ulid: str
          ULID of the Project this funding line belongs to.
      - label: str
          Human-facing label for this funding line, e.g.:
            "US DOL Stand Down 2026 grant"
            "Sutter Lakeside in-kind food"

    Optional:
      - source_kind: str
          Governance / reporting classifier, e.g.:
            "grant_reimbursement"
            "sponsor_cash"
            "sponsor_in_kind"
            "internal_operations"
          This is not enforced here beyond being a non-empty string if present.
      - fund_archetype_key: str
          Key from policy_funding.json describing the *intended* bucket
          for this funding line, e.g. "general_unrestricted",
          "grant_reimbursement". Can be left NULL at first and filled
          in later once Governance policy is clearer.
      - expected_amount_cents: int
          Planned amount in cents. May be NULL; if provided, must be
          >= 0. For in-kind support, this is the estimated fair value.
      - is_in_kind: bool
          True for in-kind support (food, goods, services). False or
          omitted for purely monetary support.
      - expected_sponsor_hint: str
          Human hint about the expected source, PII-light, e.g.
            "Sutter Lakeside Hospital"
            "Internal unrestricted + local-only pool"
          Sponsors slice will later map this to actual Sponsor records.
      - notes: str
          Free-text notes about this funding line.
      - actor_ulid: str
          Actor ULID making this change (for ledger / audit only).
      - request_id: str
          Correlation id (e.g. HTTP request id); if omitted, the
          ProjectFundingPlan ULID is used as request id in the event.

    Behavior
    --------
    * Ensures the Project exists.
    * Normalizes and validates basic shapes:
        - label must be non-empty string.
        - if expected_amount_cents is provided, it must be >= 0.
    * Inserts a ProjectFundingPlan row.
    * Emits a Calendar event on the event bus (PII-free).
    * Returns a dict that can be used as a ProjectFundingPlanDTO.

    Raises
    ------
    ValueError:
        For malformed input (missing project_ulid/label,
        negative expected_amount_cents, etc.).
    LookupError:
        If project_ulid does not refer to an existing Project.
    """
    project_ulid = (payload.get("project_ulid") or "").strip()
    if not project_ulid:
        raise ValueError("project_ulid is required")

    project = db.session.get(Project, project_ulid)
    if project is None:
        raise LookupError(f"project {project_ulid!r} not found")

    label = (payload.get("label") or "").strip()
    if not label:
        raise ValueError("label is required")

    # Optional classifiers
    source_kind = (payload.get("source_kind") or "").strip() or None
    fund_archetype_key = (
        payload.get("fund_archetype_key") or ""
    ).strip() or None

    # Optional expected amount
    expected_amount_cents_raw = payload.get("expected_amount_cents")
    expected_amount_cents: int | None
    if expected_amount_cents_raw is None:
        expected_amount_cents = None
    else:
        try:
            expected_amount_cents = int(expected_amount_cents_raw)
        except (TypeError, ValueError):
            raise ValueError(
                "expected_amount_cents must be an int if provided"
            )
        if expected_amount_cents < 0:
            raise ValueError("expected_amount_cents must be >= 0")

    # Optional flags / hints
    is_in_kind = bool(payload.get("is_in_kind") or False)
    expected_sponsor_hint = (
        payload.get("expected_sponsor_hint") or ""
    ).strip() or None
    notes = (payload.get("notes") or "").strip() or None

    pf = ProjectFundingPlan(
        project_ulid=project_ulid,
        label=label,
        source_kind=source_kind,
        fund_archetype_key=fund_archetype_key,
        expected_amount_cents=expected_amount_cents,
        is_in_kind=is_in_kind,
        expected_sponsor_hint=expected_sponsor_hint,
        notes=notes,
    )

    db.session.add(pf)
    db.session.commit()

    actor_ulid = payload.get("actor_ulid")
    request_id = payload.get("request_id") or pf.ulid

    # Optional but recommended: ledger-style event for audit
    event_bus.emit(
        domain="calendar",
        operation="calendar.project_funding_plan.created",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=pf.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": project_ulid,
        },
        meta={
            "label": label,
            "source_kind": source_kind,
            "fund_archetype_key": fund_archetype_key,
            "expected_amount_cents": expected_amount_cents,
            "is_in_kind": is_in_kind,
        },
        chain_key="calendar.project_funding",
    )

    return {
        "ulid": pf.ulid,
        "project_ulid": pf.project_ulid,
        "label": pf.label,
        "source_kind": pf.source_kind,
        "fund_archetype_key": pf.fund_archetype_key,
        "expected_amount_cents": pf.expected_amount_cents,
        "is_in_kind": pf.is_in_kind,
        "expected_sponsor_hint": pf.expected_sponsor_hint,
        "notes": pf.notes,
        "created_at_utc": pf.created_at_utc,
        "updated_at_utc": pf.updated_at_utc,
    }


# -----------------
# View Project
# -----------------


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


# -----------------
# Resolve Fund Summary
# -----------------


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


def _funding_plan_view(plan: ProjectFundingPlan) -> dict:
    """
    PII-free projection of a ProjectFundingPlan row.
    """
    return {
        "ulid": plan.ulid,
        "project_ulid": plan.project_ulid,
        "label": plan.label,
        "source_kind": plan.source_kind,
        "fund_archetype_key": plan.fund_archetype_key,
        "expected_amount_cents": plan.expected_amount_cents,
        "is_in_kind": plan.is_in_kind,
        "expected_sponsor_hint": plan.expected_sponsor_hint,
        "notes": plan.notes,
        "created_at_utc": plan.created_at_utc,
        "updated_at_utc": plan.updated_at_utc,
    }


# -----------------
# List Fund Plans
# -----------------


def list_funding_plans_for_project(project_ulid: str) -> list[dict]:
    """
    Return all funding plan lines for a given project as plain dicts.
    """
    plans = (
        db.session.query(ProjectFundingPlan)
        .filter_by(project_ulid=project_ulid)
        .order_by(ProjectFundingPlan.created_at_utc.asc())
        .all()
    )
    return [_funding_plan_view(p) for p in plans]


# -----------------
# List Project for
# a given period
# -----------------


def list_projects_for_period(period_label: str) -> list[dict]:
    """
    Return Calendar projects for a given period as plain dicts
    (ProjectDTO shape).
    """
    # If you haven't added period_label to Project yet, you can either:
    #  - add that column and filter on it, or
    #  - temporarily ignore the filter and return all projects.
    q = db.session.query(Project)

    if hasattr(Project, "period_label"):
        q = q.filter(Project.period_label == period_label)

    projects = q.order_by(Project.project_title.asc()).all()
    return [project_view(p.ulid) for p in projects]
