# app/extensions/contracts/calendar_v2.py

# ------------------
# NOTE:
#
# Do not rely on this module for policy decisions.
# The policy itself still lives in calendar.services.is_blackout,
# which reads policy_calendar.json
# ------------------

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, TypedDict

from app.extensions.errors import ContractError

# -----------------
# ContractError Handling
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=msg,
            http_status=400,
        )
    if isinstance(exc, PermissionError):
        return ContractError(
            code="permission_denied",
            where=where,
            message=msg,
            http_status=403,
        )
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found",
            where=where,
            message=msg,
            http_status=404,
        )

    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# -----------------
# Validation Helpers
# -----------------


def _require_str(name: str, value: str | None) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_ulid(name: str, value: str | None) -> str:
    v = _require_str(name, value)
    if len(v) != 26:
        raise ValueError(f"{name} must be a 26-char ULID")
    return v


def _require_int_ge(name: str, value: Any, minval: int = 0) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an int")
    if value < minval:
        raise ValueError(f"{name} must be >= {minval}")
    return value


def _require_int_gt(name: str, value: Any, minval: int = 0) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an int")
    if value <= minval:
        raise ValueError(f"{name} must be > {minval}")
    return value


def _optional_ulid(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_ulid(name, value)


def _optional_str(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_str(name, value)


def _require_str_tuple(
    name: str,
    value: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} must be a tuple/list of strings")

    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} must contain only non-empty strings")
        out.append(item.strip())
    return tuple(out)


# -----------------
# DTO's & Helpers
# (new paradigm)
# -----------------


@dataclass(frozen=True)
class FundingDemandDTO:
    funding_demand_ulid: str
    project_ulid: str
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    eligible_fund_codes: tuple[str, ...]


@dataclass(frozen=True)
class FundingSourceProfileSummaryDTO:
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
class FundingDemandPublishedSnapshotDTO:
    funding_demand_ulid: str
    project_ulid: str
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    published_at_utc: str


@dataclass(frozen=True)
class FundingDemandOriginSnapshotDTO:
    demand_draft_ulid: str | None
    budget_snapshot_ulid: str | None
    project_ulid: str


@dataclass(frozen=True)
class PublishedFundingDemandPackageDTO:
    schema_version: int
    demand: FundingDemandPublishedSnapshotDTO
    origin: FundingDemandOriginSnapshotDTO
    planning: FundingDemandPlanningSnapshotDTO
    policy: FundingDemandPolicySnapshotDTO
    workflow: FundingDemandWorkflowCuesDTO


@dataclass(frozen=True)
class FundingDemandPlanningSnapshotDTO:
    project_title: str
    spending_class: str
    tag_any: tuple[str, ...]
    source_profile_key: str | None
    ops_support_planned: bool | None
    planning_basis: str


@dataclass(frozen=True)
class FundingDemandPolicySnapshotDTO:
    decision_fingerprint: str
    eligible_fund_codes: tuple[str, ...]
    default_restriction_keys: tuple[str, ...]
    source_profile_summary: FundingSourceProfileSummaryDTO


@dataclass(frozen=True)
class FundingDemandWorkflowCuesDTO:
    receive_posture: str | None
    reserve_on_receive_expected: bool | None
    reimbursement_expected: bool | None
    bridge_support_possible: bool | None
    return_unused_posture: str | None
    recommended_income_kind: str | None
    allowed_realization_modes: tuple[str, ...]


@dataclass(frozen=True)
class FundingDemandContextDTO:
    schema_version: int
    demand: FundingDemandPublishedSnapshotDTO
    planning: FundingDemandPlanningSnapshotDTO
    policy: FundingDemandPolicySnapshotDTO
    workflow: FundingDemandWorkflowCuesDTO


@dataclass(frozen=True)
class FundingDemandExecutionTruthDTO:
    funding_demand_ulid: str
    project_ulid: str | None
    received_cents: int
    reserved_cents: int
    encumbered_cents: int
    spent_cents: int
    remaining_open_cents: int
    funded_enough: bool
    support_source_posture: str
    received_by_fund: tuple[object, ...]
    reserved_by_fund: tuple[object, ...]
    encumbered_by_fund: tuple[object, ...]
    spent_by_expense_kind: tuple[object, ...]
    income_by_income_kind: tuple[object, ...]
    ops_float_incoming_open_by_fund: tuple[object, ...]
    ops_float_outgoing_open_by_fund: tuple[object, ...]
    income_journal_ulids: tuple[str, ...]
    expense_journal_ulids: tuple[str, ...]
    reserve_ulids: tuple[str, ...]
    encumbrance_ulids: tuple[str, ...]
    ops_float_ulids: tuple[str, ...]


@dataclass(frozen=True)
class OpsFloatAllocationRequestDTO:
    source_funding_demand_ulid: str
    dest_funding_demand_ulid: str
    fund_code: str
    amount_cents: int
    support_mode: str
    memo: str | None = None
    source_ref_ulid: str | None = None
    actor_ulid: str | None = None
    actor_rbac_roles: tuple[str, ...] = ()
    actor_domain_roles: tuple[str, ...] = ()
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class OpsFloatAllocationDTO:
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
class OpsFloatSettlementRequestDTO:
    parent_ops_float_ulid: str
    amount_cents: int
    memo: str | None = None
    source_ref_ulid: str | None = None
    actor_ulid: str | None = None
    actor_rbac_roles: tuple[str, ...] = ()
    actor_domain_roles: tuple[str, ...] = ()
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class OpsFloatSettlementDTO:
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
class ProjectEncumbranceRequestDTO:
    funding_demand_ulid: str
    amount_cents: int
    fund_code: str
    expense_kind: str
    happened_at_utc: str
    source_ref_ulid: str | None = None
    memo: str | None = None
    actor_ulid: str | None = None
    actor_rbac_roles: tuple[str, ...] = ()
    actor_domain_roles: tuple[str, ...] = ()
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ProjectEncumbranceDTO:
    funding_demand_ulid: str
    project_ulid: str | None
    fund_code: str
    amount_cents: int
    encumbrance_ulid: str
    decision_fingerprint: str
    status: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectSpendRequestDTO:
    encumbrance_ulid: str
    amount_cents: int
    expense_kind: str
    payment_method: str
    happened_at_utc: str
    source_ref_ulid: str | None = None
    payee_entity_ulid: str | None = None
    memo: str | None = None
    actor_ulid: str | None = None
    actor_rbac_roles: tuple[str, ...] = ()
    actor_domain_roles: tuple[str, ...] = ()
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ProjectSpendDTO:
    funding_demand_ulid: str
    project_ulid: str | None
    encumbrance_ulid: str
    journal_ulid: str
    amount_cents: int
    decision_fingerprint: str
    status: str
    flags: tuple[str, ...] = ()


# -----------------
# Project Planning
# DTO's
# -----------------
"""
These are vestages of early Project Planning Development
This is not part of project funding flow

"""


class ProjectDTO(TypedDict):
    ulid: str
    title: str
    status: str
    fund_profile_key: str
    phase_code: str | None
    owner_ulid: str | None
    created_at_utc: str
    updated_at_utc: str


class TaskDTO(TypedDict):
    ulid: str
    project_ulid: str
    title: str
    detail: str | None
    task_kind: str | None
    estimate_cents: int | None
    hours_est_minutes: int | None
    notes_txt: str | None
    requirements_json: dict | list | None
    assigned_to_ulid: str | None
    due_at_utc: str | None
    done_at_utc: str | None
    status: str
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class CultivationOutcomeDTO:
    task_ulid: str
    project_ulid: str
    sponsor_entity_ulid: str
    workflow: str
    status: str
    task_title: str
    due_at_utc: str | None
    done_at_utc: str | None
    funding_demand_ulid: str | None
    outcome_note: str | None
    follow_up_recommended: bool
    off_cadence_follow_up_signal: bool
    funding_interest_signal: bool


class CalendarGateDTO(TypedDict):
    ok: bool
    label: str | None
    reason: str  # ok|calendar_blackout|calendar_unavailable


class ProjectFundingPlanDTO(TypedDict):
    ulid: str
    project_ulid: str
    label: str
    source_kind: str | None
    expected_amount_cents: int | None
    is_in_kind: bool
    expected_sponsor_hint: str | None
    notes: str | None
    created_at_utc: str
    updated_at_utc: str


class ProjectBudgetSummaryDTO(TypedDict):
    pass


__schema__ = {
    "blackout_ok": {
        "requires": ["when_iso?"],
        "returns_keys": ["ok", "label", "reason"],
    }
}


# -----------------
# Funding Demand
# & Fulfillment
# -----------------


def _load_provider(where: str):
    """
    Calendar slice must provide a read-only function with this signature:

        get_funding_demand(funding_demand_ulid: str) -> dict[str, Any]

    Expected keys:
      funding_demand_ulid, project_ulid, title, status, goal_cents,
      deadline_date, eligible_fund_codes
    """
    try:
        mod = importlib.import_module("app.slices.calendar.services_funding")
        fn = mod.get_funding_demand
        return fn
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            code="provider_missing",
            where=where,
            message=(
                "Calendar provider missing: "
                "app.slices.calendar.services_funding.get_funding_demand"
            ),
            http_status=500,
        ) from exc


def get_funding_demand(funding_demand_ulid: str) -> FundingDemandDTO:
    where = "calendar_v2.get_funding_demand"
    try:
        funding_demand_ulid = _require_ulid(
            "funding_demand_ulid",
            funding_demand_ulid,
        )

        provider = _load_provider(where)
        raw = provider(funding_demand_ulid)

        eligible = tuple(raw.get("eligible_fund_codes") or ())
        return FundingDemandDTO(
            funding_demand_ulid=str(raw["funding_demand_ulid"]),
            project_ulid=str(raw["project_ulid"]),
            title=str(raw.get("title") or ""),
            status=str(raw.get("status") or "unknown"),
            goal_cents=int(raw.get("goal_cents") or 0),
            deadline_date=raw.get("deadline_date"),
            eligible_fund_codes=eligible,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def get_funding_demand_context(
    funding_demand_ulid: str,
) -> FundingDemandContextDTO:
    where = "calendar_v2.get_funding_demand_context"
    try:
        pkg = get_published_funding_demand_package(funding_demand_ulid)
        return FundingDemandContextDTO(
            schema_version=pkg.schema_version,
            demand=pkg.demand,
            planning=pkg.planning,
            policy=pkg.policy,
            workflow=pkg.workflow,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def _obj_get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_published_funding_demand_package(
    raw: dict[str, Any],
) -> PublishedFundingDemandPackageDTO:
    demand_raw = raw["demand"]
    origin_raw = raw.get("origin") or {}
    planning_raw = raw["planning"]
    policy_raw = raw["policy"]
    summary_raw = policy_raw["source_profile_summary"]
    workflow_raw = raw["workflow"]

    return PublishedFundingDemandPackageDTO(
        schema_version=int(raw["schema_version"]),
        demand=FundingDemandPublishedSnapshotDTO(
            funding_demand_ulid=str(demand_raw["funding_demand_ulid"]),
            project_ulid=str(demand_raw["project_ulid"]),
            title=str(demand_raw["title"]),
            status=str(demand_raw["status"]),
            goal_cents=int(demand_raw["goal_cents"]),
            deadline_date=demand_raw.get("deadline_date"),
            published_at_utc=str(demand_raw["published_at_utc"]),
        ),
        origin=FundingDemandOriginSnapshotDTO(
            demand_draft_ulid=origin_raw.get("demand_draft_ulid"),
            budget_snapshot_ulid=origin_raw.get("budget_snapshot_ulid"),
            project_ulid=str(
                origin_raw.get("project_ulid") or demand_raw["project_ulid"]
            ),
        ),
        planning=FundingDemandPlanningSnapshotDTO(
            project_title=str(planning_raw["project_title"]),
            spending_class=str(planning_raw["spending_class"]),
            tag_any=_require_str_tuple(
                "planning.tag_any",
                planning_raw.get("tag_any"),
            ),
            source_profile_key=planning_raw.get("source_profile_key"),
            ops_support_planned=planning_raw.get("ops_support_planned"),
            planning_basis=str(planning_raw["planning_basis"]),
        ),
        policy=FundingDemandPolicySnapshotDTO(
            decision_fingerprint=str(policy_raw["decision_fingerprint"]),
            eligible_fund_codes=_require_str_tuple(
                "policy.eligible_fund_codes",
                policy_raw.get("eligible_fund_codes"),
            ),
            default_restriction_keys=_require_str_tuple(
                "policy.default_restriction_keys",
                policy_raw.get("default_restriction_keys"),
            ),
            source_profile_summary=FundingSourceProfileSummaryDTO(
                key=str(summary_raw["key"]),
                source_kind=str(summary_raw["source_kind"]),
                support_mode=str(summary_raw["support_mode"]),
                approval_posture=str(summary_raw["approval_posture"]),
                default_restriction_keys=_require_str_tuple(
                    "policy.source_profile_summary.default_restriction_keys",
                    summary_raw.get("default_restriction_keys"),
                ),
                bridge_allowed=bool(summary_raw["bridge_allowed"]),
                repayment_expectation=str(
                    summary_raw["repayment_expectation"]
                ),
                forgiveness_rule=str(summary_raw["forgiveness_rule"]),
                auto_ops_bridge_on_publish=bool(
                    summary_raw["auto_ops_bridge_on_publish"]
                ),
            ),
        ),
        workflow=FundingDemandWorkflowCuesDTO(
            receive_posture=workflow_raw.get("receive_posture"),
            reserve_on_receive_expected=workflow_raw.get(
                "reserve_on_receive_expected"
            ),
            reimbursement_expected=workflow_raw.get("reimbursement_expected"),
            bridge_support_possible=workflow_raw.get(
                "bridge_support_possible"
            ),
            return_unused_posture=workflow_raw.get("return_unused_posture"),
            recommended_income_kind=workflow_raw.get(
                "recommended_income_kind"
            ),
            allowed_realization_modes=_require_str_tuple(
                "workflow.allowed_realization_modes",
                workflow_raw.get("allowed_realization_modes"),
            ),
        ),
    )


def get_published_funding_demand_package(
    funding_demand_ulid: str,
) -> PublishedFundingDemandPackageDTO:
    where = "calendar_v2.get_published_funding_demand_package"
    try:
        funding_demand_ulid = _require_ulid(
            "funding_demand_ulid",
            funding_demand_ulid,
        )
        mod = importlib.import_module("app.slices.calendar.services_funding")
        fn = mod.get_funding_demand_context
        raw = fn(funding_demand_ulid)
        return _to_published_funding_demand_package(raw)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def encumber_project_funds(
    req: ProjectEncumbranceRequestDTO,
) -> ProjectEncumbranceDTO:
    where = "calendar_v2.encumber_project_funds"
    try:
        funding_demand_ulid = _require_ulid(
            "funding_demand_ulid",
            req.funding_demand_ulid,
        )
        amount_cents = _require_int_gt("amount_cents", req.amount_cents)
        fund_code = _require_str("fund_code", req.fund_code)
        expense_kind = _require_str("expense_kind", req.expense_kind)
        happened_at_utc = _require_str(
            "happened_at_utc",
            req.happened_at_utc,
        )
        source_ref_ulid = _optional_ulid(
            "source_ref_ulid",
            req.source_ref_ulid,
        )
        actor_ulid = _optional_ulid("actor_ulid", req.actor_ulid)
        actor_rbac_roles = _require_str_tuple(
            "actor_rbac_roles",
            req.actor_rbac_roles,
        )
        actor_domain_roles = _require_str_tuple(
            "actor_domain_roles",
            req.actor_domain_roles,
        )
        request_id = _optional_str("request_id", req.request_id)

        mod = importlib.import_module(
            "app.slices.calendar.services_finance_bridge"
        )
        fn = mod.encumber_project_funds
        out = fn(
            funding_demand_ulid=funding_demand_ulid,
            amount_cents=amount_cents,
            fund_code=fund_code,
            expense_kind=expense_kind,
            happened_at_utc=happened_at_utc,
            source_ref_ulid=source_ref_ulid,
            memo=req.memo,
            actor_ulid=actor_ulid,
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
            request_id=request_id,
            dry_run=bool(req.dry_run),
        )
        return ProjectEncumbranceDTO(
            funding_demand_ulid=out.funding_demand_ulid,
            project_ulid=out.project_ulid,
            fund_code=out.fund_code,
            amount_cents=out.amount_cents,
            encumbrance_ulid=out.encumbrance_ulid,
            decision_fingerprint=out.decision_fingerprint,
            status=out.status,
            flags=out.flags,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def spend_project_funds(req: ProjectSpendRequestDTO) -> ProjectSpendDTO:
    where = "calendar_v2.spend_project_funds"
    try:
        encumbrance_ulid = _require_ulid(
            "encumbrance_ulid",
            req.encumbrance_ulid,
        )
        amount_cents = _require_int_gt("amount_cents", req.amount_cents)
        expense_kind = _require_str("expense_kind", req.expense_kind)
        payment_method = _require_str(
            "payment_method",
            req.payment_method,
        )
        happened_at_utc = _require_str(
            "happened_at_utc",
            req.happened_at_utc,
        )
        source_ref_ulid = _optional_ulid(
            "source_ref_ulid",
            req.source_ref_ulid,
        )
        payee_entity_ulid = _optional_ulid(
            "payee_entity_ulid",
            req.payee_entity_ulid,
        )
        actor_ulid = _optional_ulid("actor_ulid", req.actor_ulid)
        actor_rbac_roles = _require_str_tuple(
            "actor_rbac_roles",
            req.actor_rbac_roles,
        )
        actor_domain_roles = _require_str_tuple(
            "actor_domain_roles",
            req.actor_domain_roles,
        )
        request_id = _optional_str("request_id", req.request_id)

        mod = importlib.import_module(
            "app.slices.calendar.services_finance_bridge"
        )
        fn = mod.spend_project_funds
        out = fn(
            encumbrance_ulid=encumbrance_ulid,
            amount_cents=amount_cents,
            expense_kind=expense_kind,
            payment_method=payment_method,
            happened_at_utc=happened_at_utc,
            source_ref_ulid=source_ref_ulid,
            payee_entity_ulid=payee_entity_ulid,
            memo=req.memo,
            actor_ulid=actor_ulid,
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
            request_id=request_id,
            dry_run=bool(req.dry_run),
        )
        return ProjectSpendDTO(
            funding_demand_ulid=out.funding_demand_ulid,
            project_ulid=out.project_ulid,
            encumbrance_ulid=out.encumbrance_ulid,
            journal_ulid=out.journal_ulid,
            amount_cents=out.amount_cents,
            decision_fingerprint=out.decision_fingerprint,
            status=out.status,
            flags=out.flags,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def get_project_execution_truth(
    *,
    funding_demand_ulid: str,
) -> FundingDemandExecutionTruthDTO:
    where = "calendar_v2.get_project_execution_truth"
    try:
        funding_demand_ulid = _require_ulid(
            "funding_demand_ulid",
            funding_demand_ulid,
        )
        mod = importlib.import_module(
            "app.slices.calendar.services_finance_bridge"
        )
        fn = mod.get_project_execution_truth
        out = fn(funding_demand_ulid=funding_demand_ulid)
        return FundingDemandExecutionTruthDTO(
            funding_demand_ulid=out.funding_demand_ulid,
            project_ulid=out.project_ulid,
            received_cents=int(out.received_cents or 0),
            reserved_cents=int(out.reserved_cents or 0),
            encumbered_cents=int(out.encumbered_cents or 0),
            spent_cents=int(out.spent_cents or 0),
            remaining_open_cents=int(out.remaining_open_cents or 0),
            funded_enough=bool(out.funded_enough),
            support_source_posture=str(out.support_source_posture),
            received_by_fund=tuple(out.received_by_fund or ()),
            reserved_by_fund=tuple(out.reserved_by_fund or ()),
            encumbered_by_fund=tuple(out.encumbered_by_fund or ()),
            spent_by_expense_kind=tuple(out.spent_by_expense_kind or ()),
            income_by_income_kind=tuple(out.income_by_income_kind or ()),
            ops_float_incoming_open_by_fund=tuple(
                out.ops_float_incoming_open_by_fund or ()
            ),
            ops_float_outgoing_open_by_fund=tuple(
                out.ops_float_outgoing_open_by_fund or ()
            ),
            income_journal_ulids=tuple(out.income_journal_ulids or ()),
            expense_journal_ulids=tuple(out.expense_journal_ulids or ()),
            reserve_ulids=tuple(out.reserve_ulids or ()),
            encumbrance_ulids=tuple(out.encumbrance_ulids or ()),
            ops_float_ulids=tuple(out.ops_float_ulids or ()),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def list_published_funding_demands(
    *,
    project_ulid: str | None = None,
    status: str = "published",
) -> tuple[FundingDemandDTO, ...]:
    where = "calendar_v2.list_published_funding_demands"
    try:
        if project_ulid is not None:
            project_ulid = _require_ulid("project_ulid", project_ulid)
        status = _require_str("status", status)

        mod = importlib.import_module("app.slices.calendar.services_funding")
        fn = mod.list_published_funding_demands

        raw_rows = fn(project_ulid=project_ulid, status=status)
        out: list[FundingDemandDTO] = []

        for raw in raw_rows:
            eligible = tuple(_obj_get(raw, "eligible_fund_codes", ()) or ())
            out.append(
                FundingDemandDTO(
                    funding_demand_ulid=str(
                        _obj_get(raw, "funding_demand_ulid")
                    ),
                    project_ulid=str(_obj_get(raw, "project_ulid")),
                    title=str(_obj_get(raw, "title", "") or ""),
                    status=str(
                        _obj_get(raw, "status", "unknown") or "unknown"
                    ),
                    goal_cents=int(_obj_get(raw, "goal_cents", 0) or 0),
                    deadline_date=_obj_get(raw, "deadline_date"),
                    eligible_fund_codes=eligible,
                )
            )
        return tuple(out)
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def allocate_ops_float_to_project(
    req: OpsFloatAllocationRequestDTO,
) -> OpsFloatAllocationDTO:
    where = "calendar_v2.allocate_ops_float_to_project"
    try:
        source_funding_demand_ulid = _require_ulid(
            "source_funding_demand_ulid",
            req.source_funding_demand_ulid,
        )
        dest_funding_demand_ulid = _require_ulid(
            "dest_funding_demand_ulid",
            req.dest_funding_demand_ulid,
        )
        fund_code = _require_str("fund_code", req.fund_code)
        amount_cents = _require_int_gt("amount_cents", req.amount_cents)
        support_mode = _require_str("support_mode", req.support_mode)
        source_ref_ulid = _optional_ulid(
            "source_ref_ulid",
            req.source_ref_ulid,
        )
        actor_ulid = _optional_ulid("actor_ulid", req.actor_ulid)
        actor_rbac_roles = _require_str_tuple(
            "actor_rbac_roles",
            req.actor_rbac_roles,
        )
        actor_domain_roles = _require_str_tuple(
            "actor_domain_roles",
            req.actor_domain_roles,
        )
        request_id = _optional_str("request_id", req.request_id)

        mod = importlib.import_module(
            "app.slices.calendar.services_ops_float"
        )
        fn = mod.allocate_ops_float_to_project
        out = fn(
            source_funding_demand_ulid=source_funding_demand_ulid,
            dest_funding_demand_ulid=dest_funding_demand_ulid,
            fund_code=fund_code,
            amount_cents=amount_cents,
            support_mode=support_mode,
            memo=req.memo,
            source_ref_ulid=source_ref_ulid,
            actor_ulid=actor_ulid,
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
            request_id=request_id,
            dry_run=bool(req.dry_run),
        )
        return OpsFloatAllocationDTO(
            source_funding_demand_ulid=out.source_funding_demand_ulid,
            dest_funding_demand_ulid=out.dest_funding_demand_ulid,
            source_project_ulid=out.source_project_ulid,
            dest_project_ulid=out.dest_project_ulid,
            fund_code=out.fund_code,
            amount_cents=out.amount_cents,
            support_mode=out.support_mode,
            ops_float_ulid=out.ops_float_ulid,
            decision_fingerprint=out.decision_fingerprint,
            status=out.status,
            flags=out.flags,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def _validate_ops_float_settlement_request(
    req: OpsFloatSettlementRequestDTO,
) -> dict[str, Any]:
    return {
        "parent_ops_float_ulid": _require_ulid(
            "parent_ops_float_ulid",
            req.parent_ops_float_ulid,
        ),
        "amount_cents": _require_int_gt("amount_cents", req.amount_cents),
        "source_ref_ulid": _optional_ulid(
            "source_ref_ulid",
            req.source_ref_ulid,
        ),
        "actor_ulid": _optional_ulid("actor_ulid", req.actor_ulid),
        "actor_rbac_roles": _require_str_tuple(
            "actor_rbac_roles",
            req.actor_rbac_roles,
        ),
        "actor_domain_roles": _require_str_tuple(
            "actor_domain_roles",
            req.actor_domain_roles,
        ),
        "request_id": _optional_str("request_id", req.request_id),
        "memo": req.memo,
        "dry_run": bool(req.dry_run),
    }


def repay_ops_float_to_operations(
    req: OpsFloatSettlementRequestDTO,
) -> OpsFloatSettlementDTO:
    where = "calendar_v2.repay_ops_float_to_operations"
    try:
        vals = _validate_ops_float_settlement_request(req)

        mod = importlib.import_module(
            "app.slices.calendar.services_ops_float"
        )
        fn = getattr(mod, "repay_ops_float_to_operations")
        out = fn(**vals)
        return OpsFloatSettlementDTO(
            parent_ops_float_ulid=out.parent_ops_float_ulid,
            ops_float_ulid=out.ops_float_ulid,
            action=out.action,
            support_mode=out.support_mode,
            source_funding_demand_ulid=out.source_funding_demand_ulid,
            source_project_ulid=out.source_project_ulid,
            dest_funding_demand_ulid=out.dest_funding_demand_ulid,
            dest_project_ulid=out.dest_project_ulid,
            fund_code=out.fund_code,
            amount_cents=out.amount_cents,
            decision_fingerprint=out.decision_fingerprint,
            flags=out.flags,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def forgive_ops_float_shortfall(
    req: OpsFloatSettlementRequestDTO,
) -> OpsFloatSettlementDTO:
    where = "calendar_v2.forgive_ops_float_shortfall"
    try:
        vals = _validate_ops_float_settlement_request(req)

        mod = importlib.import_module(
            "app.slices.calendar.services_ops_float"
        )
        fn = getattr(mod, "forgive_ops_float_shortfall")
        out = fn(**vals)

        return OpsFloatSettlementDTO(
            parent_ops_float_ulid=out.parent_ops_float_ulid,
            ops_float_ulid=out.ops_float_ulid,
            action=out.action,
            support_mode=out.support_mode,
            source_funding_demand_ulid=out.source_funding_demand_ulid,
            source_project_ulid=out.source_project_ulid,
            dest_funding_demand_ulid=out.dest_funding_demand_ulid,
            dest_project_ulid=out.dest_project_ulid,
            fund_code=out.fund_code,
            amount_cents=out.amount_cents,
            decision_fingerprint=out.decision_fingerprint,
            flags=out.flags,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


# -----------------
# Calendar slice
# Blackout Check
# -----------------


def blackout_ok(when_iso: str | None = None) -> CalendarGateDTO:
    where = "calendar_v2.blackout_ok"
    try:
        from app.slices.calendar import services as svc

        when = when_iso.strip() if isinstance(when_iso, str) else None
        if when == "":
            raise ValueError("when_iso must be non-empty if provided")

        blocked = svc.is_blackout(
            when_iso=when
        )  # <-- service should accept None
        return {
            "ok": not blocked,
            "label": "blackout" if blocked else None,
            "reason": "calendar_blackout" if blocked else "ok",
        }
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Project Planning
# Context Only
# NOT Funding Flow
# -----------------
"""
These are vestages of early Project Planning Development
This is not part of project funding flow

"""


def create_project(
    *,
    project_title: str,
    fund_profile_key: str | None = None,
    owner_ulid: str | None = None,
    phase_code: str | None = None,
    status: str | None = None,
    actor_ulid: str,
    request_id: str,
) -> ProjectDTO:
    where = "calendar_v2.create_project"
    try:
        project_title = _require_str("project_title", project_title)
        if owner_ulid is not None:
            owner_ulid = _require_ulid("owner_ulid", owner_ulid)
        if status is None:
            status = "planned"
        else:
            status = _require_str("status", status)

        from app.slices.calendar import services as svc

        payload = {
            "project_title": project_title,
            "fund_profile_key": fund_profile_key,
            "owner_ulid": owner_ulid,
            "phase_code": phase_code,
            "status": status,
        }

        return svc.create_project(
            payload,
            actor_ulid=actor_ulid,
            request_id=request_id,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def find_project_by_title(*, project_title: str) -> ProjectDTO | None:
    where = "calendar_v2.find_project_by_title"
    try:
        project_title = _require_str("project_title", project_title)

        from app.slices.calendar import services as svc

        return svc.find_project_by_title(project_title)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def create_project_funding_plan(
    *,
    project_ulid: str,
    label: str,
    source_kind: str | None = None,
    fund_archetype_key: str | None = None,
    expected_amount_cents: int | None = None,
    is_in_kind: bool = False,
    expected_sponsor_hint: str | None = None,
    notes: str | None = None,
    actor_ulid: str | None = None,
    request_id: str | None = None,
) -> ProjectFundingPlanDTO:
    """
    Create a ProjectFundingPlan row for a Calendar Project.

    Thin contract wrapper around
    :func:`app.slices.calendar.services.create_project_funding_plan`.

    Responsibilities:
      * Validate argument shapes (ULIDs, strings, ints where applicable).
      * Shape arguments into a payload dict for the Calendar slice.
      * Delegate to the Calendar service implementation.
      * Map any underlying errors into a canonical ContractError.
    """
    where = "calendar_v2.create_project_funding_plan"
    try:
        project_ulid = _require_ulid("project_ulid", project_ulid)
        label = _require_str("label", label)

        if source_kind is not None:
            source_kind = _require_str("source_kind", source_kind)
        if fund_archetype_key is not None:
            fund_archetype_key = _require_str(
                "fund_archetype_key", fund_archetype_key
            )

        if expected_amount_cents is not None:
            expected_amount_cents = _require_int_ge(
                "expected_amount_cents", expected_amount_cents, minval=0
            )

        from app.slices.calendar import services as svc

        payload: dict[str, Any] = {
            "project_ulid": project_ulid,
            "label": label,
            "source_kind": source_kind,
            "fund_archetype_key": fund_archetype_key,
            "expected_amount_cents": expected_amount_cents,
            "is_in_kind": bool(is_in_kind),
            "expected_sponsor_hint": expected_sponsor_hint,
            "notes": notes,
            "actor_ulid": actor_ulid,
            "request_id": request_id,
        }

        return svc.create_project_funding_plan(
            payload, actor_ulid=actor_ulid, request_id=request_id
        )

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def create_task(
    *,
    project_ulid: str,
    task_title: str,
    actor_ulid: str,
    request_id: str,
    task_detail: str | None = None,
    task_kind: str | None = None,
    estimate_cents: int | None = None,
    hours_est_minutes: int | None = None,
    notes_txt: str | None = None,
    requirements_json: dict | list | None = None,
    assigned_to_ulid: str | None = None,
    due_at_utc: str | None = None,
) -> TaskDTO:
    where = "calendar_v2.create_task"
    try:
        project_ulid = _require_ulid("project_ulid", project_ulid)
        task_title = _require_str("task_title", task_title)
        actor_ulid = _require_ulid("actor_ulid", actor_ulid)
        request_id = _require_str("request_id", request_id)

        if assigned_to_ulid is not None:
            assigned_to_ulid = _require_ulid(
                "assigned_to_ulid",
                assigned_to_ulid,
            )
        if task_kind is not None:
            task_kind = _require_str("task_kind", task_kind)
        if task_detail is not None:
            task_detail = _require_str("task_detail", task_detail)
        if notes_txt is not None:
            notes_txt = _require_str("notes_txt", notes_txt)
        if due_at_utc is not None:
            due_at_utc = _require_str("due_at_utc", due_at_utc)
        if estimate_cents is not None:
            estimate_cents = _require_int_ge(
                "estimate_cents",
                estimate_cents,
                minval=0,
            )
        if hours_est_minutes is not None:
            hours_est_minutes = _require_int_ge(
                "hours_est_minutes",
                hours_est_minutes,
                minval=0,
            )

        from app.slices.calendar import services as svc

        return svc.create_task(
            project_ulid=project_ulid,
            task_title=task_title,
            actor_ulid=actor_ulid,
            request_id=request_id,
            task_detail=task_detail,
            task_kind=task_kind,
            estimate_cents=estimate_cents,
            hours_est_minutes=hours_est_minutes,
            notes_txt=notes_txt,
            requirements_json=requirements_json,
            assigned_to_ulid=assigned_to_ulid,
            due_at_utc=due_at_utc,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_cultivation_outcomes_for_sponsor(
    *,
    sponsor_entity_ulid: str,
    limit: int = 10,
) -> tuple[CultivationOutcomeDTO, ...]:
    where = "calendar_v2.list_cultivation_outcomes_for_sponsor"
    try:
        sponsor_entity_ulid = _require_ulid(
            "sponsor_entity_ulid",
            sponsor_entity_ulid,
        )
        limit = _require_int_ge("limit", limit, minval=1)

        from app.slices.calendar import services as svc

        rows = svc.list_cultivation_outcomes_for_sponsor(
            sponsor_entity_ulid,
            limit=limit,
        )

        return tuple(
            CultivationOutcomeDTO(
                task_ulid=str(row["task_ulid"]),
                project_ulid=str(row["project_ulid"]),
                sponsor_entity_ulid=str(row["sponsor_entity_ulid"]),
                workflow=str(row["workflow"]),
                status=str(row["status"]),
                task_title=str(row["task_title"]),
                due_at_utc=row.get("due_at_utc"),
                done_at_utc=row.get("done_at_utc"),
                funding_demand_ulid=row.get("funding_demand_ulid"),
                outcome_note=row.get("outcome_note"),
                follow_up_recommended=bool(row.get("follow_up_recommended")),
                off_cadence_follow_up_signal=bool(
                    row.get("off_cadence_follow_up_signal")
                ),
                funding_interest_signal=bool(
                    row.get("funding_interest_signal")
                ),
            )
            for row in rows
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_cultivation_outcomes_for_demand(
    *,
    funding_demand_ulid: str,
    limit: int = 20,
) -> tuple[CultivationOutcomeDTO, ...]:
    where = "calendar_v2.list_cultivation_outcomes_for_demand"
    try:
        funding_demand_ulid = _require_ulid(
            "funding_demand_ulid",
            funding_demand_ulid,
        )
        limit = _require_int_ge("limit", limit, 1)

        from app.slices.calendar import services as svc

        rows = svc.list_cultivation_outcomes_for_demand(
            funding_demand_ulid,
            limit=limit,
        )

        return tuple(
            CultivationOutcomeDTO(
                task_ulid=str(row["task_ulid"]),
                project_ulid=str(row["project_ulid"]),
                sponsor_entity_ulid=str(row["sponsor_entity_ulid"]),
                workflow=str(row["workflow"]),
                status=str(row["status"]),
                task_title=str(row["task_title"]),
                due_at_utc=row.get("due_at_utc"),
                done_at_utc=row.get("done_at_utc"),
                funding_demand_ulid=row.get("funding_demand_ulid"),
                outcome_note=row.get("outcome_note"),
                follow_up_recommended=bool(row.get("follow_up_recommended")),
                off_cadence_follow_up_signal=bool(
                    row.get("off_cadence_follow_up_signal")
                ),
                funding_interest_signal=bool(
                    row.get("funding_interest_signal")
                ),
            )
            for row in rows
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_cultivation_outcome(
    *,
    task_ulid: str,
) -> CultivationOutcomeDTO | None:
    where = "calendar_v2.get_cultivation_outcome"
    try:
        task_ulid = _require_ulid("task_ulid", task_ulid)

        from app.slices.calendar import services as svc

        row = svc.get_cultivation_outcome(task_ulid)
        if row is None:
            return None

        return CultivationOutcomeDTO(
            task_ulid=str(row["task_ulid"]),
            project_ulid=str(row["project_ulid"]),
            sponsor_entity_ulid=str(row["sponsor_entity_ulid"]),
            workflow=str(row["workflow"]),
            status=str(row["status"]),
            task_title=str(row["task_title"]),
            due_at_utc=row.get("due_at_utc"),
            done_at_utc=row.get("done_at_utc"),
            funding_demand_ulid=row.get("funding_demand_ulid"),
            outcome_note=row.get("outcome_note"),
            follow_up_recommended=bool(row.get("follow_up_recommended")),
            off_cadence_follow_up_signal=bool(
                row.get("off_cadence_follow_up_signal")
            ),
            funding_interest_signal=bool(row.get("funding_interest_signal")),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_project_funding_plans(
    *, project_ulid: str
) -> list[ProjectFundingPlanDTO]:
    """
    Contract entry point: list all funding plan lines for a project.

    This is a read-only view over Calendar.ProjectFundingPlan, used
    by Governance and Sponsors to understand planned funding sources.

    Args:
        project_ulid:
            ULID of the Calendar project.

    Returns:
        list[ProjectFundingPlanDTO]

    Raises:
        ContractError:
            - code="bad_argument" if project_ulid is malformed.
            - code="internal_error" for unexpected failures.
    """
    where = "calendar_v2.list_project_funding_plans"
    try:
        project_ulid = _require_ulid("project_ulid", project_ulid)

        from app.slices.calendar import services as svc

        return svc.list_funding_plans_for_project(project_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_projects_for_period(*, period_label: str) -> list[ProjectDTO]:
    """
    Contract entry point: list projects for a given period.

    Calendar owns the semantics of period_label (e.g. "2026",
    "FY2026"). Governance and Sponsors treat it as an opaque key.

    Args:
        period_label:
            Period/budget label used by Calendar & Governance.

    Returns:
        list[ProjectDTO]

    Raises:
        ContractError:
            - code="bad_argument" if period_label is blank.
            - code="internal_error" for unexpected failures.
    """
    where = "calendar_v2.list_projects_for_period"
    try:
        period_label = _require_str("period_label", period_label)

        from app.slices.calendar import services as svc

        return svc.list_projects_for_period(period_label)
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


__all__ = [
    "FundingDemandDTO",
    "OpsFloatAllocationRequestDTO",
    "OpsFloatAllocationDTO",
    "OpsFloatSettlementRequestDTO",
    "OpsFloatSettlementDTO",
    "ProjectEncumbranceRequestDTO",
    "ProjectEncumbranceDTO",
    "ProjectSpendRequestDTO",
    "ProjectSpendDTO",
    "TaskDTO",
    "FundingDemandOriginSnapshotDTO",
    "PublishedFundingDemandPackageDTO",
    "FundingDemandExecutionTruthDTO",
    "get_project_execution_truth",
    "get_published_funding_demand_package",
    "get_funding_demand",
    "get_funding_demand_context",
    "get_cultivation_outcome",
    "list_cultivation_outcomes_for_demand",
    "list_cultivation_outcomes_for_sponsor",
    "list_published_funding_demands",
    "encumber_project_funds",
    "spend_project_funds",
    "allocate_ops_float_to_project",
    "repay_ops_float_to_operations",
    "forgive_ops_float_shortfall",
    "blackout_ok",
    "create_project",
    "find_project_by_title",
    "create_task",
    "create_project_funding_plan",
    "list_project_funding_plans",
    "list_projects_for_period",
]
