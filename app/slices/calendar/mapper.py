# app/slices/calendar/mapper.py
"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FundingDemandView:
    funding_demand_ulid: str
    project_ulid: str | None
    project_title: str | None
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    spending_class: str | None
    eligible_fund_keys: tuple[str, ...]
    tag_any: tuple[str, ...]
    published_at_utc: str | None
    closed_at_utc: str | None
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class PublishedFundingDemandListItemView:
    funding_demand_ulid: str
    project_ulid: str | None
    project_title: str | None
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    eligible_fund_keys: tuple[str, ...]


@dataclass(frozen=True)
class ProjectEncumbranceResult:
    funding_demand_ulid: str
    project_ulid: str | None
    fund_key: str
    amount_cents: int
    encumbrance_ulid: str
    decision_fingerprint: str
    status: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectSpendResult:
    funding_demand_ulid: str
    project_ulid: str | None
    encumbrance_ulid: str
    journal_ulid: str
    amount_cents: int
    decision_fingerprint: str
    status: str
    flags: tuple[str, ...] = ()

def funding_demand_to_view(row) -> FundingDemandView:
    project = getattr(row, "project", None)
    project_title = None
    if project is not None:
        project_title = getattr(project, "project_title", None)

    eligible = tuple(row.eligible_fund_keys_json or ())
    tags = tuple(row.tag_any_json or ())

    return FundingDemandView(
        funding_demand_ulid=row.ulid,
        project_ulid=row.project_ulid,
        project_title=project_title,
        title=row.title,
        status=row.status,
        goal_cents=int(row.goal_cents or 0),
        deadline_date=row.deadline_date,
        spending_class=row.spending_class,
        eligible_fund_keys=eligible,
        tag_any=tags,
        published_at_utc=row.published_at_utc,
        closed_at_utc=row.closed_at_utc,
        created_at_utc=row.created_at_utc,
        updated_at_utc=row.updated_at_utc,
    )


def funding_demand_to_contract_dto(row) -> dict[str, object]:
    return {
        "funding_demand_ulid": row.ulid,
        "project_ulid": row.project_ulid,
        "title": row.title,
        "status": row.status,
        "goal_cents": int(row.goal_cents or 0),
        "deadline_date": row.deadline_date,
        "eligible_fund_keys": list(row.eligible_fund_keys_json or ()),
    }


def funding_demand_to_list_item(row) -> PublishedFundingDemandListItemView:
    project = getattr(row, "project", None)
    project_title = None
    if project is not None:
        project_title = getattr(project, "project_title", None)

    return PublishedFundingDemandListItemView(
        funding_demand_ulid=row.ulid,
        project_ulid=row.project_ulid,
        project_title=project_title,
        title=row.title,
        status=row.status,
        goal_cents=int(row.goal_cents or 0),
        deadline_date=row.deadline_date,
        eligible_fund_keys=tuple(row.eligible_fund_keys_json or ()),
    )
