# app/slices/calendar/services_funding.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts import governance_v2 as gov
from app.lib.chrono import now_iso8601_ms

from .mapper import (
    funding_demand_to_contract_dto,
    funding_demand_to_list_item,
    funding_demand_to_view,
)
from .models import FundingDemand, Project
from .taxonomy import FUNDING_DEMAND_STATUSES

_ALLOWED_STATUS = set(FUNDING_DEMAND_STATUSES)


@dataclass(frozen=True)
class ProjectPolicyHints:
    source_profile_key: str | None = None
    ops_support_planned: bool | None = None


_EMPTY_POLICY_HINTS = ProjectPolicyHints()


def _normalize_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    for part in raw.split(","):
        tag = part.strip()
        if not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _require_status(status: str) -> str:
    if status not in _ALLOWED_STATUS:
        raise ValueError(f"invalid funding demand status: {status}")
    return status


def _get_project_or_raise(project_ulid: str) -> Project:
    row = db.session.execute(
        select(Project).where(Project.ulid == project_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"project not found: {project_ulid}")
    return row


def _row_field(row: object, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _load_project_funding_plan_rows(project_ulid: str) -> list[object]:
    try:
        from app.slices.calendar import services as calendar_services

        list_fn = getattr(
            calendar_services,
            "list_funding_plans_for_project",
            None,
        )
        if list_fn is None:
            return []
        rows = list_fn(project_ulid) or []
        return list(rows)
    except Exception:
        return []


def _derive_project_policy_hints(rows: list[object]) -> ProjectPolicyHints:
    profile_keys: set[str] = set()
    ops_support_planned: bool | None = None

    for row in rows:
        profile_key = _row_field(row, "source_profile_key")
        if profile_key:
            profile_keys.add(str(profile_key).strip())

        planned = _row_field(row, "ops_support_planned")
        if isinstance(planned, bool):
            if ops_support_planned is None:
                ops_support_planned = planned
            else:
                ops_support_planned = ops_support_planned or planned

    source_profile_key = None
    if len(profile_keys) == 1:
        source_profile_key = next(iter(profile_keys))

    return ProjectPolicyHints(
        source_profile_key=source_profile_key,
        ops_support_planned=ops_support_planned,
    )


def _project_policy_hints(project_ulid: str | None) -> ProjectPolicyHints:
    """
    Return Calendar-owned policy cues for a project.

    Calendar derives these cues from its Funding Plan rows and passes
    them to Governance as advisory preview inputs. Governance remains
    the authority for semantic validation, selector behavior, and
    authorization.
    """
    if not project_ulid:
        return _EMPTY_POLICY_HINTS

    rows = _load_project_funding_plan_rows(project_ulid)
    if not rows:
        return _EMPTY_POLICY_HINTS

    return _derive_project_policy_hints(rows)


def _build_funding_decision_request(
    *,
    row: FundingDemand,
    op: str,
    amount_cents: int,
    funding_demand_ulid: str,
    project_ulid: str | None,
    spending_class: str | None,
    income_kind: str | None = None,
    expense_kind: str | None = None,
    restriction_keys: tuple[str, ...] = (),
    demand_eligible_fund_keys: tuple[str, ...] = (),
    tag_any: tuple[str, ...] = (),
    selected_fund_key: str | None = None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
) -> gov.FundingDecisionRequestDTO:
    effective_project_ulid = project_ulid or row.project_ulid
    effective_spending_class = spending_class or row.spending_class
    hints = _project_policy_hints(effective_project_ulid)

    return gov.FundingDecisionRequestDTO(
        op=op,
        amount_cents=int(amount_cents),
        funding_demand_ulid=funding_demand_ulid,
        project_ulid=effective_project_ulid,
        spending_class=effective_spending_class,
        income_kind=income_kind,
        expense_kind=expense_kind,
        source_profile_key=hints.source_profile_key,
        restriction_keys=tuple(restriction_keys or ()),
        demand_eligible_fund_keys=tuple(demand_eligible_fund_keys or ()),
        tag_any=tuple(tag_any or ()),
        selected_fund_key=selected_fund_key,
        ops_support_planned=hints.ops_support_planned,
        actor_rbac_roles=tuple(actor_rbac_roles or ()),
        actor_domain_roles=tuple(actor_domain_roles or ()),
    )


def _project_choices() -> list[tuple[str, str]]:
    rows = db.session.execute(
        select(Project).order_by(Project.project_title.asc())
    ).scalars()
    return [(r.ulid, r.project_title) for r in rows]


def list_projects_for_form() -> list[tuple[str, str]]:
    return _project_choices()


def get_spending_class_choices() -> list[tuple[str, str]]:
    tx = gov.get_finance_taxonomy()
    vals = list(getattr(tx, "spending_classes", []) or [])
    return [("", "— Select —"), *[(v.key, v.label) for v in vals]]


def create_funding_demand(
    payload: dict[str, Any],
    *,
    actor_ulid: str | None,
    request_id: str | None,
) -> FundingDemand:
    project_ulid = str(payload.get("project_ulid") or "").strip()
    title = str(payload.get("title") or "").strip()
    goal_cents = int(payload.get("goal_cents") or 0)
    deadline_date = payload.get("deadline_date")
    spending_class = payload.get("spending_class")
    tag_any = payload.get("tag_any")

    if not project_ulid:
        raise ValueError("project_ulid is required")
    if not title:
        raise ValueError("title is required")
    if goal_cents < 0:
        raise ValueError("goal_cents must be >= 0")

    _get_project_or_raise(project_ulid)

    if spending_class:
        res = gov.validate_semantic_keys(
            spending_class=spending_class,
        )
        if not res.ok:
            raise ValueError(
                "; ".join(res.errors) or "invalid spending_class"
            )

    if hasattr(deadline_date, "isoformat"):
        deadline_date = deadline_date.isoformat()

    row = FundingDemand(
        project_ulid=project_ulid,
        title=title,
        status="draft",
        goal_cents=goal_cents,
        deadline_date=deadline_date,
        spending_class=spending_class or None,
        eligible_fund_keys_json=[],
        tag_any_json=_normalize_tags(tag_any),
        published_at_utc=None,
        closed_at_utc=None,
    )
    db.session.add(row)
    db.session.flush()

    event_bus.emit(
        domain="calendar",
        operation="funding_demand_created",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"project_ulid": row.project_ulid},
        changed={
            "fields": [
                "project_ulid",
                "title",
                "status",
                "goal_cents",
                "deadline_date",
                "spending_class",
                "eligible_fund_keys_json",
                "tag_any_json",
                "published_at_utc",
                "closed_at_utc",
            ]
        },
    )
    return row


def update_funding_demand(
    funding_demand_ulid: str,
    payload: dict[str, Any],
    *,
    actor_ulid: str | None,
    request_id: str | None,
) -> FundingDemand:
    row = _get_demand_or_raise(funding_demand_ulid)

    project_ulid = str(payload.get("project_ulid") or "").strip()
    title = str(payload.get("title") or "").strip()
    goal_cents = int(payload.get("goal_cents") or 0)
    deadline_date = payload.get("deadline_date")
    spending_class = payload.get("spending_class")
    tag_any = payload.get("tag_any")

    if not project_ulid:
        raise ValueError("project_ulid is required")
    if not title:
        raise ValueError("title is required")
    if goal_cents < 0:
        raise ValueError("goal_cents must be >= 0")

    _get_project_or_raise(project_ulid)

    if spending_class:
        res = gov.validate_semantic_keys(
            spending_class=spending_class,
        )
        if not res.ok:
            raise ValueError(
                "; ".join(res.errors) or "invalid spending_class"
            )

    if hasattr(deadline_date, "isoformat"):
        deadline_date = deadline_date.isoformat()

    row.project_ulid = project_ulid
    row.title = title
    row.goal_cents = goal_cents
    row.deadline_date = deadline_date
    row.spending_class = spending_class or None
    row.tag_any_json = _normalize_tags(tag_any)

    db.session.flush()

    event_bus.emit(
        domain="calendar",
        operation="funding_demand_updated",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"project_ulid": row.project_ulid},
        changed={
            "fields": [
                "project_ulid",
                "title",
                "goal_cents",
                "deadline_date",
                "spending_class",
                "tag_any_json",
            ]
        },
    )
    return row


def publish_funding_demand(
    funding_demand_ulid: str,
    *,
    actor_ulid: str | None,
    request_id: str | None,
) -> FundingDemand:
    row = _get_demand_or_raise(funding_demand_ulid)

    if row.status == "closed":
        raise ValueError("cannot publish a closed funding demand")
    if not row.project_ulid:
        raise ValueError("funding demand must have project_ulid")
    if not row.spending_class:
        raise ValueError("spending_class is required before publish")

    preview_req = _build_funding_decision_request(
        row=row,
        op="encumber",
        amount_cents=int(row.goal_cents or 0),
        funding_demand_ulid=row.ulid,
        project_ulid=row.project_ulid,
        spending_class=row.spending_class,
        income_kind=None,
        expense_kind=None,
        restriction_keys=(),
        demand_eligible_fund_keys=tuple(row.eligible_fund_keys_json or ()),
        tag_any=tuple(row.tag_any_json or ()),
        selected_fund_key=None,
        actor_rbac_roles=(),
        actor_domain_roles=(),
    )
    preview = gov.preview_funding_decision(preview_req)

    row.eligible_fund_keys_json = list(preview.eligible_fund_keys)
    row.status = "published"
    row.published_at_utc = now_iso8601_ms()

    db.session.flush()

    event_bus.emit(
        domain="calendar",
        operation="funding_demand_published",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": row.project_ulid,
            "decision_fingerprint": preview.decision_fingerprint,
        },
        changed={
            "fields": [
                "status",
                "eligible_fund_keys_json",
                "published_at_utc",
            ]
        },
        meta={
            "required_approvals": list(preview.required_approvals),
        },
    )
    return row


def unpublish_funding_demand(
    funding_demand_ulid: str,
    *,
    actor_ulid: str | None,
    request_id: str | None,
) -> FundingDemand:
    row = _get_demand_or_raise(funding_demand_ulid)
    if row.status == "closed":
        raise ValueError("cannot unpublish a closed funding demand")

    row.status = "draft"
    row.published_at_utc = None

    db.session.flush()

    event_bus.emit(
        domain="calendar",
        operation="funding_demand_unpublished",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"project_ulid": row.project_ulid},
        changed={"fields": ["status", "published_at_utc"]},
    )
    return row


def get_funding_demand(funding_demand_ulid: str) -> dict[str, object]:
    row = _get_demand_or_raise(funding_demand_ulid)
    return funding_demand_to_contract_dto(row)


def get_funding_demand_view(
    funding_demand_ulid: str,
):
    row = _get_demand_or_raise(funding_demand_ulid)
    return funding_demand_to_view(row)


def list_published_funding_demands(
    *,
    project_ulid: str | None = None,
    status: str = "published",
) -> list[dict[str, object]]:
    _require_status(status)

    stmt = select(FundingDemand).where(FundingDemand.status == status)
    if project_ulid:
        stmt = stmt.where(FundingDemand.project_ulid == project_ulid)

    rows = db.session.execute(
        stmt.order_by(
            FundingDemand.deadline_date.asc(), FundingDemand.title.asc()
        )
    ).scalars()

    out: list[dict[str, object]] = []
    for row in rows:
        item = funding_demand_to_list_item(row)
        out.append(
            {
                "funding_demand_ulid": item.funding_demand_ulid,
                "project_ulid": item.project_ulid,
                "project_title": item.project_title,
                "title": item.title,
                "status": item.status,
                "goal_cents": item.goal_cents,
                "deadline_date": item.deadline_date,
                "eligible_fund_keys": list(item.eligible_fund_keys),
            }
        )
    return out


def _get_demand_or_raise(funding_demand_ulid: str) -> FundingDemand:
    row = db.session.execute(
        select(FundingDemand).where(FundingDemand.ulid == funding_demand_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"funding demand not found: {funding_demand_ulid}")
    return row


def list_funding_demands(
    *,
    project_ulid: str | None = None,
    status: str | None = None,
) -> list:
    stmt = select(FundingDemand)

    if project_ulid:
        stmt = stmt.where(FundingDemand.project_ulid == project_ulid)

    if status:
        _require_status(status)
        stmt = stmt.where(FundingDemand.status == status)

    rows = db.session.execute(
        stmt.order_by(
            FundingDemand.deadline_date.asc(),
            FundingDemand.created_at_utc.desc(),
            FundingDemand.title.asc(),
        )
    ).scalars()

    return [funding_demand_to_list_item(row) for row in rows]


def list_funding_demands_view(
    *,
    project_ulid: str | None = None,
    status: str | None = None,
) -> list:
    return list_funding_demands(
        project_ulid=project_ulid,
        status=status,
    )


def get_funding_demand_status_choices() -> list[tuple[str, str]]:
    return [
        ("", "All statuses"),
        ("draft", "draft"),
        ("published", "published"),
        ("funding_in_progress", "funding_in_progress"),
        ("funded", "funded"),
        ("executing", "executing"),
        ("closed", "closed"),
    ]
