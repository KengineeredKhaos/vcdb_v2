# app/slices/calendar/services_funding.py

"""Calendar funding read-side + canonical published-context helpers.

This module is intentionally read-side only.
Direct FundingDemand draft/publish mutators are retired.
The canonical downstream package is the frozen published_context_json
written at DemandDraft promotion time.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import governance_v2 as gov

from .mapper import (
    FundingSourceProfileSummaryView,
    funding_demand_to_contract_dto,
    funding_demand_to_list_item,
    funding_demand_to_view,
)
from .models import FundingDemand, Project


def _clean_text(
    value: str | None, *, default: str | None = None
) -> str | None:
    text = str(value or "").strip()
    if text:
        return text
    return default


def _normalize_str_list(
    raw: list[str] | tuple[str, ...] | str | None
) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",")]
    else:
        items = [str(x).strip() for x in raw]

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _normalize_str_tuple(
    raw: list[str] | tuple[str, ...] | str | None,
) -> tuple[str, ...]:
    return tuple(_normalize_str_list(raw))


def _merge_str_tuples(
    *values: tuple[str, ...] | list[str] | str | None
) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        for item in _normalize_str_list(value):
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
    return tuple(out)


def _get_project_or_raise(project_ulid: str) -> Project:
    row = db.session.execute(
        select(Project).where(Project.ulid == project_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"project not found: {project_ulid}")
    return row


def _get_demand_or_raise(funding_demand_ulid: str) -> FundingDemand:
    row = db.session.execute(
        select(FundingDemand).where(FundingDemand.ulid == funding_demand_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"funding demand not found: {funding_demand_ulid}")
    return row


def _summary_get(obj, attr: str, default=None):
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _build_source_profile_summary_view(
    *,
    source_profile_key: str | None,
) -> FundingSourceProfileSummaryView:
    if not source_profile_key:
        raise ValueError(
            "source_profile_key is required for published context"
        )

    dto = gov.get_funding_source_profile_summary(str(source_profile_key))

    return FundingSourceProfileSummaryView(
        key=_summary_get(dto, "key", str(source_profile_key)),
        source_kind=_summary_get(dto, "source_kind", ""),
        support_mode=_summary_get(dto, "support_mode", ""),
        approval_posture=_summary_get(dto, "approval_posture", ""),
        default_restriction_keys=tuple(
            _summary_get(dto, "default_restriction_keys", ()) or ()
        ),
        bridge_allowed=bool(_summary_get(dto, "bridge_allowed", False)),
        repayment_expectation=str(
            _summary_get(dto, "repayment_expectation", "") or ""
        ).strip(),
        forgiveness_rule=str(
            _summary_get(dto, "forgiveness_rule", "") or ""
        ).strip(),
        auto_ops_bridge_on_publish=bool(
            _summary_get(dto, "auto_ops_bridge_on_publish", False)
        ),
    )


def _derive_receive_posture(source_kind: str, support_mode: str) -> str:
    if source_kind == "cash_support" and support_mode in {
        "direct_cash",
        "restricted_grant_cash",
    }:
        return "direct_support"
    if (
        source_kind == "reimbursement_support"
        and support_mode == "reimbursement_promise"
    ):
        return "reimbursement_expected"
    if source_kind == "in_kind_support" and support_mode == "in_kind_offset":
        return "in_kind_offset"
    if source_kind == "operations_support" and support_mode == "ops_seed":
        return "ops_seed"
    if source_kind == "operations_support" and support_mode == "ops_backfill":
        return "ops_backfill"
    if source_kind == "operations_support" and support_mode == "ops_bridge":
        return "ops_bridge"
    return "direct_support"


def _derive_workflow_from_profile(
    summary: FundingSourceProfileSummaryView,
) -> dict[str, Any]:
    receive_posture = _derive_receive_posture(
        summary.source_kind,
        summary.support_mode,
    )
    reimbursement_expected = bool(
        summary.source_kind == "reimbursement_support"
        or summary.support_mode == "reimbursement_promise"
        or summary.repayment_expectation == "reimbursement_expected"
    )
    bridge_support_possible = bool(summary.bridge_allowed)

    if receive_posture == "direct_support":
        reserve_on_receive_expected = True
        recommended_income_kind = (
            "grant_disbursement"
            if summary.support_mode == "restricted_grant_cash"
            else "donation"
        )
        allowed_realization_modes = ["donation", "pledge"]
    elif receive_posture == "reimbursement_expected":
        reserve_on_receive_expected = False
        recommended_income_kind = "reimbursement"
        allowed_realization_modes = ["pledge", "reimbursement_receipt"]
    elif receive_posture == "in_kind_offset":
        reserve_on_receive_expected = False
        recommended_income_kind = "inkind"
        allowed_realization_modes = ["donation"]
    elif receive_posture in {"ops_seed", "ops_backfill"}:
        reserve_on_receive_expected = False
        recommended_income_kind = "other"
        allowed_realization_modes = ["pledge"]
    elif receive_posture == "ops_bridge":
        reserve_on_receive_expected = False
        recommended_income_kind = "other"
        allowed_realization_modes = ["pledge", "reimbursement_receipt"]
    else:
        reserve_on_receive_expected = False
        recommended_income_kind = None
        allowed_realization_modes = []

    return {
        "receive_posture": receive_posture,
        "reserve_on_receive_expected": reserve_on_receive_expected,
        "reimbursement_expected": reimbursement_expected,
        "bridge_support_possible": bridge_support_possible,
        "return_unused_posture": str(summary.forgiveness_rule or "").strip()
        or None,
        "recommended_income_kind": recommended_income_kind,
        "allowed_realization_modes": allowed_realization_modes,
    }


def build_canonical_published_context_payload(
    *,
    funding_demand_ulid: str,
    project_ulid: str,
    project_title: str | None,
    title: str,
    status: str,
    goal_cents: int,
    deadline_date: str | None,
    published_at_utc: str,
    demand_draft_ulid: str | None,
    budget_snapshot_ulid: str | None,
    summary: str | None,
    scope_summary: str | None,
    source_profile_key: str | None,
    ops_support_planned: bool | None,
    spending_class: str | None,
    tag_any: list[str] | tuple[str, ...] | str | None,
    eligible_fund_codes: list[str] | tuple[str, ...] | str | None,
    default_restriction_keys: list[str] | tuple[str, ...] | str | None,
    decision_fingerprint: str | None = None,
    approved_tag_any: list[str] | tuple[str, ...] | str | None = None,
) -> dict[str, Any]:
    source_summary = _build_source_profile_summary_view(
        source_profile_key=source_profile_key,
    )
    workflow = _derive_workflow_from_profile(source_summary)

    approved_tags = _merge_str_tuples(approved_tag_any, tag_any)
    eligible_codes = _normalize_str_tuple(eligible_fund_codes)
    default_restrictions = _merge_str_tuples(
        default_restriction_keys,
        source_summary.default_restriction_keys,
    )

    return {
        "schema_version": 1,
        "demand": {
            "funding_demand_ulid": funding_demand_ulid,
            "project_ulid": project_ulid,
            "title": str(title or "").strip(),
            "status": str(status or "").strip(),
            "goal_cents": int(goal_cents or 0),
            "deadline_date": _clean_text(deadline_date),
            "published_at_utc": str(published_at_utc or "").strip(),
        },
        "origin": {
            "demand_draft_ulid": _clean_text(demand_draft_ulid),
            "budget_snapshot_ulid": _clean_text(budget_snapshot_ulid),
            "project_ulid": project_ulid,
        },
        "planning": {
            "project_title": _clean_text(project_title, default="") or "",
            "summary": _clean_text(summary),
            "scope_summary": _clean_text(scope_summary),
            "spending_class": _clean_text(spending_class, default="") or "",
            "tag_any": list(_normalize_str_tuple(tag_any)),
            "source_profile_key": _clean_text(source_profile_key),
            "ops_support_planned": ops_support_planned,
            "planning_basis": "budget_snapshot",
        },
        "policy": {
            "decision_fingerprint": str(decision_fingerprint or "").strip(),
            "eligible_fund_codes": list(eligible_codes),
            "default_restriction_keys": list(default_restrictions),
            "approved_tag_any": list(approved_tags),
            "source_profile_summary": {
                "key": source_summary.key,
                "source_kind": source_summary.source_kind,
                "support_mode": source_summary.support_mode,
                "approval_posture": source_summary.approval_posture,
                "default_restriction_keys": list(
                    source_summary.default_restriction_keys
                ),
                "bridge_allowed": source_summary.bridge_allowed,
                "repayment_expectation": source_summary.repayment_expectation,
                "forgiveness_rule": source_summary.forgiveness_rule,
                "auto_ops_bridge_on_publish": source_summary.auto_ops_bridge_on_publish,
            },
        },
        "workflow": workflow,
    }


def _canonicalize_published_context(row: FundingDemand) -> dict[str, Any]:
    payload = row.published_context_json or {}
    if not isinstance(payload, dict):
        raise ValueError("published_context_json must be an object")

    demand = dict(payload.get("demand") or {})
    origin = dict(payload.get("origin") or {})
    planning = dict(payload.get("planning") or {})
    policy = dict(payload.get("policy") or {})
    workflow = dict(payload.get("workflow") or {})

    project = getattr(row, "project", None)
    project_title = planning.get("project_title")
    if not project_title and project is not None:
        project_title = getattr(project, "project_title", None)

    source_profile_key = (
        planning.get("source_profile_key")
        or policy.get("source_profile_key")
        or (dict(policy.get("source_profile_summary") or {})).get("key")
        or getattr(project, "funding_profile_key", None)
    )

    if not source_profile_key:
        raise ValueError(
            "published demand context missing source_profile_key"
        )

    source_summary = _build_source_profile_summary_view(
        source_profile_key=source_profile_key,
    )
    source_summary_json = dict(policy.get("source_profile_summary") or {})
    if not source_summary_json:
        source_summary_json = {
            "key": source_summary.key,
            "source_kind": source_summary.source_kind,
            "support_mode": source_summary.support_mode,
            "approval_posture": source_summary.approval_posture,
            "default_restriction_keys": list(
                source_summary.default_restriction_keys
            ),
            "bridge_allowed": source_summary.bridge_allowed,
            "repayment_expectation": source_summary.repayment_expectation,
            "forgiveness_rule": source_summary.forgiveness_rule,
            "auto_ops_bridge_on_publish": source_summary.auto_ops_bridge_on_publish,
        }

    if not workflow:
        workflow = _derive_workflow_from_profile(source_summary)

    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "demand": {
            "funding_demand_ulid": demand.get("funding_demand_ulid")
            or row.ulid,
            "project_ulid": demand.get("project_ulid") or row.project_ulid,
            "title": demand.get("title") or str(row.title or "").strip(),
            "status": demand.get("status") or str(row.status or "").strip(),
            "goal_cents": int(
                demand.get("goal_cents") or row.goal_cents or 0
            ),
            "deadline_date": demand.get("deadline_date") or row.deadline_date,
            "published_at_utc": (
                demand.get("published_at_utc") or row.published_at_utc
            ),
        },
        "origin": {
            "demand_draft_ulid": origin.get("demand_draft_ulid")
            or getattr(row, "origin_draft_ulid", None),
            "budget_snapshot_ulid": origin.get("budget_snapshot_ulid"),
            "project_ulid": origin.get("project_ulid") or row.project_ulid,
        },
        "planning": {
            "project_title": _clean_text(project_title, default="") or "",
            "summary": planning.get("summary"),
            "scope_summary": planning.get("scope_summary"),
            "spending_class": planning.get("spending_class")
            or row.spending_class
            or "",
            "tag_any": list(
                _merge_str_tuples(planning.get("tag_any"), row.tag_any_json)
            ),
            "source_profile_key": _clean_text(source_profile_key),
            "ops_support_planned": planning.get("ops_support_planned"),
            "planning_basis": planning.get("planning_basis")
            or "budget_snapshot",
        },
        "policy": {
            "decision_fingerprint": str(
                policy.get("decision_fingerprint") or ""
            ).strip(),
            "eligible_fund_codes": list(
                _merge_str_tuples(
                    policy.get("eligible_fund_codes"),
                    row.eligible_fund_codes_json,
                )
            ),
            "default_restriction_keys": list(
                _merge_str_tuples(
                    policy.get("default_restriction_keys"),
                    source_summary.default_restriction_keys,
                )
            ),
            "approved_tag_any": list(
                _merge_str_tuples(
                    policy.get("approved_tag_any"),
                    planning.get("tag_any"),
                    row.tag_any_json,
                )
            ),
            "source_profile_summary": source_summary_json,
        },
        "workflow": {
            "receive_posture": workflow.get("receive_posture"),
            "reserve_on_receive_expected": workflow.get(
                "reserve_on_receive_expected"
            ),
            "reimbursement_expected": workflow.get("reimbursement_expected"),
            "bridge_support_possible": workflow.get(
                "bridge_support_possible"
            ),
            "return_unused_posture": workflow.get("return_unused_posture"),
            "recommended_income_kind": workflow.get(
                "recommended_income_kind"
            ),
            "allowed_realization_modes": list(
                _normalize_str_tuple(
                    workflow.get("allowed_realization_modes")
                )
            ),
        },
    }


def _build_funding_decision_request_from_context(
    *,
    row: FundingDemand,
    op: str,
    amount_cents: int,
    funding_demand_ulid: str,
    project_ulid: str | None,
    expense_kind: str | None = None,
    income_kind: str | None = None,
    restriction_keys: tuple[str, ...] = (),
    selected_fund_code: str | None = None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
) -> gov.FundingDecisionRequestDTO:
    context = _canonicalize_published_context(row)
    planning = dict(context["planning"])
    policy = dict(context["policy"])

    return gov.FundingDecisionRequestDTO(
        op=op,
        amount_cents=int(amount_cents),
        funding_demand_ulid=funding_demand_ulid,
        project_ulid=project_ulid or row.project_ulid,
        spending_class=_clean_text(planning.get("spending_class")),
        income_kind=_clean_text(income_kind),
        expense_kind=_clean_text(expense_kind),
        source_profile_key=_clean_text(planning.get("source_profile_key")),
        restriction_keys=_merge_str_tuples(
            restriction_keys,
            policy.get("default_restriction_keys"),
        ),
        ops_support_planned=planning.get("ops_support_planned"),
        demand_eligible_fund_codes=_normalize_str_tuple(
            policy.get("eligible_fund_codes")
        ),
        tag_any=_merge_str_tuples(
            policy.get("approved_tag_any"),
            planning.get("tag_any"),
        ),
        selected_fund_code=_clean_text(selected_fund_code),
        actor_rbac_roles=tuple(actor_rbac_roles or ()),
        actor_domain_roles=tuple(actor_domain_roles or ()),
    )


def list_projects_for_form() -> list[tuple[str, str]]:
    rows = db.session.execute(
        select(Project).order_by(Project.project_title.asc())
    ).scalars()
    return [(r.ulid, r.project_title) for r in rows]


def get_spending_class_choices() -> list[tuple[str, str]]:
    tx = gov.get_finance_taxonomy()
    vals = list(getattr(tx, "spending_classes", []) or [])
    return [("", "— Select —"), *[(v.key, v.label) for v in vals]]


def get_funding_demand_context(funding_demand_ulid: str) -> dict[str, object]:
    row = _get_demand_or_raise(funding_demand_ulid)
    if not row.published_context_json:
        raise ValueError("funding demand has no published context")
    return _canonicalize_published_context(row)


def get_funding_demand(funding_demand_ulid: str) -> dict[str, object]:
    row = _get_demand_or_raise(funding_demand_ulid)
    return funding_demand_to_contract_dto(row)


def get_funding_demand_view(funding_demand_ulid: str):
    row = _get_demand_or_raise(funding_demand_ulid)
    return funding_demand_to_view(row)


def list_funding_demands() -> list[object]:
    rows = db.session.execute(
        select(FundingDemand).order_by(FundingDemand.created_at_utc.desc())
    ).scalars()
    return [funding_demand_to_list_item(r) for r in rows]


def list_published_funding_demands(
    *,
    project_ulid: str | None = None,
) -> list[object]:
    stmt = (
        select(FundingDemand)
        .where(FundingDemand.status != "draft")
        .order_by(
            FundingDemand.published_at_utc.desc(),
            FundingDemand.created_at_utc.desc(),
        )
    )
    if project_ulid:
        stmt = stmt.where(FundingDemand.project_ulid == project_ulid)

    rows = db.session.execute(stmt).scalars().all()
    return [funding_demand_to_list_item(row) for row in rows]


def create_funding_demand(*args, **kwargs):
    raise RuntimeError(
        "Direct FundingDemand creation is retired. "
        "Use services_drafts.create_draft_from_snapshot(...) "
        "and promote_draft_to_funding_demand(...)."
    )


def update_funding_demand(*args, **kwargs):
    raise RuntimeError(
        "Direct FundingDemand editing is retired. Edit the DemandDraft instead."
    )


def publish_funding_demand(*args, **kwargs):
    raise RuntimeError(
        "Direct FundingDemand publish is retired. "
        "Approve and promote a DemandDraft instead."
    )


def unpublish_funding_demand(*args, **kwargs):
    raise RuntimeError(
        "Direct FundingDemand unpublish is retired. "
        "Published demands are not reverted to draft."
    )


__all__ = [
    "_build_funding_decision_request_from_context",
    "_get_demand_or_raise",
    "build_canonical_published_context_payload",
    "get_funding_demand",
    "get_funding_demand_context",
    "get_funding_demand_view",
    "get_spending_class_choices",
    "list_funding_demands",
    "list_projects_for_form",
    "list_published_funding_demands",
]
