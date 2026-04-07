# app/slices/calendar/mapper.py
"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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
    eligible_fund_codes: tuple[str, ...]
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
    eligible_fund_codes: tuple[str, ...]


@dataclass(frozen=True)
class OpsFloatAllocationResult:
    source_funding_demand_ulid: str
    dest_funding_demand_ulid: str
    source_project_ulid: str | None
    dest_project_ulid: str | None
    fund_code: str
    amount_cents: int
    support_mode: str
    ops_float_ulid: str
    decision_fingerprint: str
    status: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpsFloatSettlementResult:
    parent_ops_float_ulid: str
    ops_float_ulid: str
    action: str
    support_mode: str
    source_funding_demand_ulid: str
    source_project_ulid: str | None
    dest_funding_demand_ulid: str
    dest_project_ulid: str | None
    fund_code: str
    amount_cents: int
    decision_fingerprint: str | None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectEncumbranceResult:
    funding_demand_ulid: str
    project_ulid: str | None
    fund_code: str
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


@dataclass(frozen=True)
class FundingSourceProfileSummaryView:
    key: str
    source_kind: str
    support_mode: str
    approval_posture: str
    default_restriction_keys: tuple[str, ...]
    bridge_allowed: bool
    repayment_expectation: str
    forgiveness_rule: str
    auto_ops_bridge_on_publish: bool


@dataclass(frozen=True)
class FundingDemandPublishedSnapshotView:
    funding_demand_ulid: str
    project_ulid: str
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    published_at_utc: str


@dataclass(frozen=True)
class FundingDemandPlanningSnapshotView:
    project_title: str
    spending_class: str
    tag_any: tuple[str, ...]
    source_profile_key: str | None
    ops_support_planned: bool | None
    planning_basis: str


@dataclass(frozen=True)
class FundingDemandPolicySnapshotView:
    decision_fingerprint: str
    eligible_fund_codes: tuple[str, ...]
    default_restriction_keys: tuple[str, ...]
    source_profile_summary: FundingSourceProfileSummaryView


@dataclass(frozen=True)
class FundingDemandWorkflowCuesView:
    receive_posture: str | None
    reserve_on_receive_expected: bool | None
    reimbursement_expected: bool | None
    bridge_support_possible: bool | None
    return_unused_posture: str | None
    recommended_income_kind: str | None
    allowed_realization_modes: tuple[str, ...]


@dataclass(frozen=True)
class FundingDemandContextView:
    schema_version: int
    demand: FundingDemandPublishedSnapshotView
    planning: FundingDemandPlanningSnapshotView
    policy: FundingDemandPolicySnapshotView
    workflow: FundingDemandWorkflowCuesView


# -----------------
# DTO Builders
# -----------------


def funding_demand_context_to_json_dict(
    view: FundingDemandContextView,
) -> dict[str, Any]:
    return asdict(view)


def funding_demand_to_view(row) -> FundingDemandView:
    project = getattr(row, "project", None)
    project_title = None
    if project is not None:
        project_title = getattr(project, "project_title", None)

    eligible = tuple(row.eligible_fund_codes_json or ())
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
        eligible_fund_codes=eligible,
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
        "eligible_fund_codes": list(row.eligible_fund_codes_json or ()),
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
        eligible_fund_codes=tuple(row.eligible_fund_codes_json or ()),
    )
