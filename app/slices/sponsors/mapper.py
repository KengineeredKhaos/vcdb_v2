"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FundingOpportunityView:
    funding_demand_ulid: str
    project_ulid: str | None
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    eligible_fund_keys: tuple[str, ...]


@dataclass(frozen=True)
class SponsorFundingIntentView:
    intent_ulid: str
    sponsor_entity_ulid: str
    funding_demand_ulid: str
    intent_kind: str
    amount_cents: int
    status: str
    note: str | None
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class FundingIntentTotalsView:
    funding_demand_ulid: str
    pledged_cents: int
    pledged_by_sponsor: int
    pledge_ulids: tuple[str, ...]
    donation_ulids: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityPlanningView:
    project_title: str
    spending_class: str
    tag_any: tuple[str, ...]
    source_profile_key: str | None
    ops_support_planned: bool | None
    planning_basis: str


@dataclass(frozen=True)
class OpportunitySourceProfileView:
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
class OpportunityPolicyView:
    decision_fingerprint: str
    eligible_fund_keys: tuple[str, ...]
    default_restriction_keys: tuple[str, ...]
    source_profile_summary: OpportunitySourceProfileView


@dataclass(frozen=True)
class OpportunityWorkflowView:
    receive_posture: str | None
    reserve_on_receive_expected: bool | None
    reimbursement_expected: bool | None
    bridge_support_possible: bool | None
    return_unused_posture: str | None
    recommended_income_kind: str | None
    allowed_realization_modes: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityMoneyView:
    received_cents: int
    reserved_cents: int
    encumbered_cents: int
    spent_cents: int
    remaining_goal_cents: int
    uncovered_pipeline_gap_cents: int
    unreserved_received_cents: int


@dataclass(frozen=True)
class FundingOpportunityDetailView:
    funding_demand_ulid: str
    project_ulid: str | None
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    published_at_utc: str | None
    planning: OpportunityPlanningView
    policy: OpportunityPolicyView
    workflow: OpportunityWorkflowView
    totals: FundingIntentTotalsView
    money: OpportunityMoneyView


@dataclass(frozen=True)
class FundingRealizationDefaultsView:
    intent_ulid: str
    funding_demand_ulid: str
    project_ulid: str | None
    amount_cents: int
    source_profile_key: str | None
    ops_support_planned: bool | None
    eligible_fund_keys: tuple[str, ...]
    default_restriction_keys: tuple[str, ...]
    recommended_income_kind: str | None
    reserve_on_receive_expected: bool | None
    allowed_realization_modes: tuple[str, ...]


def calendar_demand_to_opportunity_view(dto) -> FundingOpportunityView:
    return FundingOpportunityView(
        funding_demand_ulid=dto.funding_demand_ulid,
        project_ulid=dto.project_ulid,
        title=dto.title,
        status=dto.status,
        goal_cents=int(dto.goal_cents or 0),
        deadline_date=dto.deadline_date,
        eligible_fund_keys=tuple(dto.eligible_fund_keys or ()),
    )


def sponsor_funding_intent_to_view(row) -> SponsorFundingIntentView:
    return SponsorFundingIntentView(
        intent_ulid=row.ulid,
        sponsor_entity_ulid=row.sponsor_entity_ulid,
        funding_demand_ulid=row.funding_demand_ulid,
        intent_kind=row.intent_kind,
        amount_cents=int(row.amount_cents or 0),
        status=row.status,
        note=row.note,
        created_at_utc=row.created_at_utc,
        updated_at_utc=row.updated_at_utc,
    )


def funding_intent_totals_to_view(
    raw: Mapping[str, Any],
) -> FundingIntentTotalsView:
    pledged_by_sponsor = 0
    rows = raw.get("pledged_by_sponsor") or ()
    for row in rows:
        try:
            pledged_by_sponsor += int(row.get("amount_cents") or 0)
        except Exception:
            continue

    return FundingIntentTotalsView(
        funding_demand_ulid=str(raw.get("funding_demand_ulid") or ""),
        pledged_cents=int(raw.get("pledged_cents") or 0),
        pledged_by_sponsor=pledged_by_sponsor,
        pledge_ulids=tuple(raw.get("pledge_ulids") or ()),
        donation_ulids=tuple(raw.get("donation_ulids") or ()),
    )


def funding_context_to_detail_view(
    context,
    *,
    totals: Mapping[str, Any],
    money,
) -> FundingOpportunityDetailView:
    total_goal = int(context.demand.goal_cents or 0)
    pledged_cents = int(totals.get("pledged_cents") or 0)
    received_cents = int(getattr(money, "received_cents", 0) or 0)
    reserved_cents = int(getattr(money, "reserved_cents", 0) or 0)
    encumbered_cents = int(getattr(money, "encumbered_cents", 0) or 0)
    spent_cents = int(getattr(money, "spent_cents", 0) or 0)

    remaining_goal_cents = max(total_goal - received_cents, 0)
    uncovered_pipeline_gap_cents = max(total_goal - pledged_cents, 0)
    unreserved_received_cents = max(received_cents - reserved_cents, 0)

    summary = context.policy.source_profile_summary

    return FundingOpportunityDetailView(
        funding_demand_ulid=context.demand.funding_demand_ulid,
        project_ulid=context.demand.project_ulid,
        title=context.demand.title,
        status=context.demand.status,
        goal_cents=total_goal,
        deadline_date=context.demand.deadline_date,
        published_at_utc=context.demand.published_at_utc,
        planning=OpportunityPlanningView(
            project_title=context.planning.project_title,
            spending_class=context.planning.spending_class,
            tag_any=tuple(context.planning.tag_any or ()),
            source_profile_key=context.planning.source_profile_key,
            ops_support_planned=context.planning.ops_support_planned,
            planning_basis=context.planning.planning_basis,
        ),
        policy=OpportunityPolicyView(
            decision_fingerprint=context.policy.decision_fingerprint,
            eligible_fund_keys=tuple(context.policy.eligible_fund_keys or ()),
            default_restriction_keys=tuple(
                context.policy.default_restriction_keys or ()
            ),
            source_profile_summary=OpportunitySourceProfileView(
                key=summary.key,
                source_kind=summary.source_kind,
                support_mode=summary.support_mode,
                approval_posture=summary.approval_posture,
                default_restriction_keys=tuple(
                    summary.default_restriction_keys or ()
                ),
                bridge_allowed=bool(summary.bridge_allowed),
                repayment_expectation=summary.repayment_expectation,
                forgiveness_rule=summary.forgiveness_rule,
                auto_ops_bridge_on_publish=bool(
                    summary.auto_ops_bridge_on_publish
                ),
            ),
        ),
        workflow=OpportunityWorkflowView(
            receive_posture=context.workflow.receive_posture,
            reserve_on_receive_expected=(
                context.workflow.reserve_on_receive_expected
            ),
            reimbursement_expected=(context.workflow.reimbursement_expected),
            bridge_support_possible=(
                context.workflow.bridge_support_possible
            ),
            return_unused_posture=(context.workflow.return_unused_posture),
            recommended_income_kind=(
                context.workflow.recommended_income_kind
            ),
            allowed_realization_modes=tuple(
                context.workflow.allowed_realization_modes or ()
            ),
        ),
        totals=funding_intent_totals_to_view(totals),
        money=OpportunityMoneyView(
            received_cents=received_cents,
            reserved_cents=reserved_cents,
            encumbered_cents=encumbered_cents,
            spent_cents=spent_cents,
            remaining_goal_cents=remaining_goal_cents,
            uncovered_pipeline_gap_cents=uncovered_pipeline_gap_cents,
            unreserved_received_cents=unreserved_received_cents,
        ),
    )


def funding_context_to_realization_defaults(
    context,
    *,
    intent_ulid: str,
    amount_cents: int,
) -> FundingRealizationDefaultsView:
    return FundingRealizationDefaultsView(
        intent_ulid=intent_ulid,
        funding_demand_ulid=context.demand.funding_demand_ulid,
        project_ulid=context.demand.project_ulid,
        amount_cents=int(amount_cents or 0),
        source_profile_key=context.planning.source_profile_key,
        ops_support_planned=context.planning.ops_support_planned,
        eligible_fund_keys=tuple(context.policy.eligible_fund_keys or ()),
        default_restriction_keys=tuple(
            context.policy.default_restriction_keys or ()
        ),
        recommended_income_kind=(context.workflow.recommended_income_kind),
        reserve_on_receive_expected=(
            context.workflow.reserve_on_receive_expected
        ),
        allowed_realization_modes=tuple(
            context.workflow.allowed_realization_modes or ()
        ),
    )


@dataclass(frozen=True)
class SponsorCapabilityView:
    domain: str
    key: str


@dataclass(frozen=True)
class SponsorPledgeView:
    pledge_ulid: str
    type: str
    status: str
    has_restriction: bool
    est_value_number: int | None
    currency: str | None
    updated_at_utc: str | None


@dataclass(frozen=True)
class SponsorView:
    sponsor_ulid: str
    entity_ulid: str
    onboard_step: str | None
    admin_review_required: bool
    readiness_status: str
    mou_status: str
    active_capabilities: list[SponsorCapabilityView]
    pledges: list[SponsorPledgeView]
    capability_last_update_utc: str | None
    pledge_last_update_utc: str | None
    first_seen_utc: str | None
    last_touch_utc: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


@dataclass(frozen=True)
class SponsorPOCLinkView:
    sponsor_ulid: str
    person_entity_ulid: str
    relation: str
    scope: str | None
    rank: int | None
    is_primary: bool
    org_role: str | None
    valid_from_utc: str | None
    valid_to_utc: str | None
    active: bool


@dataclass(frozen=True)
class SponsorPOCView:
    link: SponsorPOCLinkView


def map_sponsor_capability(c) -> SponsorCapabilityView:
    return SponsorCapabilityView(
        domain=getattr(c, "domain", ""),
        key=getattr(c, "key", ""),
    )


def map_sponsor_pledge(p) -> SponsorPledgeView:
    return SponsorPledgeView(
        pledge_ulid=getattr(p, "pledge_ulid", ""),
        type=getattr(p, "type", ""),
        status=getattr(p, "status", ""),
        has_restriction=bool(getattr(p, "has_restriction", False)),
        est_value_number=getattr(p, "est_value_number", None),
        currency=getattr(p, "currency", None),
        updated_at_utc=getattr(p, "updated_at_utc", None),
    )


def map_sponsor_view(
    s,
    active_caps: Sequence[object],
    pledges: Sequence[object],
) -> SponsorView:
    entity_ulid = getattr(s, "entity_ulid", "")
    return SponsorView(
        sponsor_ulid=entity_ulid,
        entity_ulid=entity_ulid,
        onboard_step=getattr(s, "onboard_step", None),
        admin_review_required=bool(
            getattr(s, "admin_review_required", False)
        ),
        readiness_status=getattr(s, "readiness_status", ""),
        mou_status=getattr(s, "mou_status", ""),
        active_capabilities=[map_sponsor_capability(c) for c in active_caps],
        pledges=[map_sponsor_pledge(p) for p in pledges],
        capability_last_update_utc=getattr(
            s, "capability_last_update_utc", None
        ),
        pledge_last_update_utc=getattr(s, "pledge_last_update_utc", None),
        first_seen_utc=getattr(s, "first_seen_utc", None),
        last_touch_utc=getattr(s, "last_touch_utc", None),
        created_at_utc=getattr(s, "created_at_utc", None),
        updated_at_utc=getattr(s, "updated_at_utc", None),
    )


def map_sponsor_poc_view(d: Mapping[str, Any]) -> SponsorPOCView:
    link_raw = d.get("link", d)
    link = link_raw if isinstance(link_raw, Mapping) else {}
    return SponsorPOCView(
        link=SponsorPOCLinkView(
            sponsor_ulid=str(link.get("sponsor_ulid", "")),
            person_entity_ulid=str(link.get("person_entity_ulid", "")),
            relation=str(link.get("relation", "")),
            scope=link.get("scope", None),
            rank=link.get("rank", None),
            is_primary=bool(link.get("is_primary", False)),
            org_role=link.get("org_role", None),
            valid_from_utc=link.get("valid_from_utc", None),
            valid_to_utc=link.get("valid_to_utc", None),
            active=bool(link.get("active", False)),
        )
    )


def map_sponsor_poc_list(
    rows: Sequence[Mapping[str, Any]],
) -> list[SponsorPOCView]:
    return [map_sponsor_poc_view(r) for r in rows]


def sponsor_view_to_dto(view: SponsorView) -> dict[str, Any]:
    return {
        "sponsor_ulid": view.sponsor_ulid,
        "entity_ulid": view.entity_ulid,
        "onboard_step": view.onboard_step,
        "admin_review_required": view.admin_review_required,
        "readiness_status": view.readiness_status,
        "mou_status": view.mou_status,
        "active_capabilities": [
            {"domain": c.domain, "key": c.key}
            for c in view.active_capabilities
        ],
        "pledges": [
            {
                "pledge_ulid": p.pledge_ulid,
                "type": p.type,
                "status": p.status,
                "has_restriction": p.has_restriction,
                "est_value_number": p.est_value_number,
                "currency": p.currency,
                "updated_at_utc": p.updated_at_utc,
            }
            for p in view.pledges
        ],
        "capability_last_update_utc": view.capability_last_update_utc,
        "pledge_last_update_utc": view.pledge_last_update_utc,
        "first_seen_utc": view.first_seen_utc,
        "last_touch_utc": view.last_touch_utc,
        "created_at_utc": view.created_at_utc,
        "updated_at_utc": view.updated_at_utc,
    }


def sponsor_poc_view_to_dto(view: SponsorPOCView) -> dict[str, Any]:
    link = view.link
    return {
        "link": {
            "sponsor_ulid": link.sponsor_ulid,
            "person_entity_ulid": link.person_entity_ulid,
            "relation": link.relation,
            "scope": link.scope,
            "rank": link.rank,
            "is_primary": link.is_primary,
            "org_role": link.org_role,
            "valid_from_utc": link.valid_from_utc,
            "valid_to_utc": link.valid_to_utc,
            "active": link.active,
        }
    }


def sponsor_poc_list_to_dto(
    views: Sequence[SponsorPOCView],
) -> list[dict[str, Any]]:
    return [sponsor_poc_view_to_dto(v) for v in views]


__all__ = [
    "FundingIntentTotalsView",
    "FundingOpportunityDetailView",
    "FundingOpportunityView",
    "FundingRealizationDefaultsView",
    "OpportunityMoneyView",
    "OpportunityPlanningView",
    "OpportunityPolicyView",
    "OpportunitySourceProfileView",
    "OpportunityWorkflowView",
    "SponsorCapabilityView",
    "SponsorFundingIntentView",
    "SponsorPOCLinkView",
    "SponsorPOCView",
    "SponsorPledgeView",
    "SponsorView",
    "SponsorPOCLinkView",
    "SponsorPOCView",
    "calendar_demand_to_opportunity_view",
    "funding_context_to_detail_view",
    "funding_context_to_realization_defaults",
    "funding_intent_totals_to_view",
    "map_sponsor_capability",
    "map_sponsor_pledge",
    "map_sponsor_poc_list",
    "map_sponsor_poc_view",
    "map_sponsor_view",
    "map_sponsor_poc_view",
    "map_sponsor_poc_list",
    "sponsor_funding_intent_to_view",
    "sponsor_poc_list_to_dto",
    "sponsor_poc_view_to_dto",
    "sponsor_view_to_dto",
    "sponsor_poc_view_to_dto",
    "sponsor_poc_list_to_dto",
]
