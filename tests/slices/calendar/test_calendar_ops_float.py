# tests/slices/calendar/test_calendar_ops_float.py

from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.contracts import (
    calendar_v2,
    finance_v2,
    governance_v2,
    sponsors_v2,
)
from app.slices.calendar.models import FundingDemand, Project
from app.slices.calendar.services_budget import (
    add_budget_line,
    create_working_snapshot,
    lock_snapshot,
)
from app.slices.calendar.services_drafts import (
    approve_draft_for_publish,
    create_draft_from_snapshot,
    mark_draft_ready_for_review,
    promote_draft_to_funding_demand,
    submit_draft_for_governance_review,
)
from app.slices.entity.models import Entity, EntityOrg
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_funding import create_funding_intent


def _create_sponsor(name: str) -> Sponsor:
    entity = Entity(kind="org")
    db.session.add(entity)
    db.session.flush()
    db.session.add(
        EntityOrg(
            entity_ulid=entity.ulid,
            legal_name=name,
        )
    )
    sponsor = Sponsor(entity_ulid=entity.ulid)
    db.session.add(sponsor)
    db.session.flush()
    return sponsor


def _create_published_demand(
    *,
    project_title: str,
    demand_title: str,
    spending_class: str = "basic_needs",
    goal_cents: int = 12000,
    source_profile_key: str = "ops_bridge_preapproved",
    ops_support_planned: bool = True,
    eligible_fund_codes: tuple[str, ...] = ("general_unrestricted",),
    default_restriction_keys: tuple[str, ...] = (),
    tag_any: tuple[str, ...] = (),
) -> str:
    project = Project(
        project_title=project_title,
        status="draft_planning",
        funding_profile_key=source_profile_key,
    )
    db.session.add(project)
    db.session.flush()

    snap = create_working_snapshot(
        project_ulid=project.ulid,
        actor_ulid=project.ulid,
        snapshot_label="Ops Float Basis",
        scope_summary="Full project scope",
    )
    add_budget_line(
        snapshot_ulid=snap["ulid"],
        actor_ulid=project.ulid,
        label="Initial project budget",
        line_kind="materials",
        estimated_total_cents=goal_cents,
    )
    lock_snapshot(
        snapshot_ulid=snap["ulid"],
        actor_ulid=project.ulid,
    )

    draft = create_draft_from_snapshot(
        project_ulid=project.ulid,
        snapshot_ulid=snap["ulid"],
        actor_ulid=project.ulid,
        title=demand_title,
        summary=f"{demand_title} funding demand",
        scope_summary="Full project scope",
        requested_amount_cents=goal_cents,
        spending_class_candidate=spending_class,
        source_profile_key=source_profile_key,
        ops_support_planned=ops_support_planned,
        tag_any=",".join(tag_any),
    )

    mark_draft_ready_for_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    submit_draft_for_governance_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    approve_draft_for_publish(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
        approved_semantics={
            "spending_class": spending_class,
            "source_profile_key": source_profile_key,
            "eligible_fund_codes": list(eligible_fund_codes),
            "default_restriction_keys": list(default_restriction_keys),
            "tag_any": list(tag_any),
        },
    )
    promoted = promote_draft_to_funding_demand(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    db.session.flush()

    funding = promoted["funding_demand"]
    return funding.get("funding_demand_ulid") or funding["ulid"]


def _realize_into_demand(funding_demand_ulid: str, amount_cents: int) -> str:
    sponsor = _create_sponsor("Ops Float Test Sponsor")
    intent = create_funding_intent(
        {
            "sponsor_entity_ulid": sponsor.entity_ulid,
            "funding_demand_ulid": funding_demand_ulid,
            "intent_kind": "donation",
            "amount_cents": amount_cents,
            "status": "committed",
            "note": "ops float source funding",
        },
        actor_ulid=None,
        request_id="req-ops-float-intent",
    )
    db.session.flush()

    tx = governance_v2.get_finance_taxonomy()
    out = sponsors_v2.realize_funding_intent(
        sponsors_v2.FundingRealizationRequestDTO(
            intent_ulid=intent.ulid,
            amount_cents=amount_cents,
            happened_at_utc="2026-03-16T18:00:00Z",
            fund_code="general_unrestricted",
            income_kind=tx.income_kinds[0].key,
            receipt_method="bank",
            reserve_on_receive=True,
            request_id="req-ops-float-realize",
        )
    )
    db.session.flush()
    return out.journal_ulid


def test_ops_float_seed_requires_governor(app):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)

        proj_fd = _create_published_demand(
            project_title="Elks Welcome Home",
            demand_title="Elks WHK Reimbursement Project",
            spending_class="basic_needs",
            source_profile_key="ops_bridge_preapproved",
            ops_support_planned=True,
        )

        with pytest.raises(Exception) as exc:
            calendar_v2.allocate_ops_float_to_project(
                calendar_v2.OpsFloatAllocationRequestDTO(
                    source_funding_demand_ulid=ops_fd,
                    dest_funding_demand_ulid=proj_fd,
                    fund_code="general_unrestricted",
                    amount_cents=5000,
                    support_mode="seed",
                    request_id="req-ops-float-seed-denied",
                )
            )

        msg = str(exc.value).lower()
        assert "approval" in msg or "permission" in msg


def test_ops_float_seed_allocation_enables_project_encumber(app):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)

        proj_fd = _create_published_demand(
            project_title="Elks Welcome Home",
            demand_title="Elks WHK Reimbursement Project",
            spending_class="basic_needs",
            source_profile_key="ops_bridge_preapproved",
            ops_support_planned=True,
        )

        alloc = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_code="general_unrestricted",
                amount_cents=5000,
                support_mode="seed",
                actor_domain_roles=("governor",),
                request_id="req-ops-float-seed-ok",
            )
        )
        db.session.flush()

        summary_dest = finance_v2.get_ops_float_summary(proj_fd)
        assert summary_dest.incoming_open_cents == 5000

        summary_src = finance_v2.get_ops_float_summary(ops_fd)
        assert summary_src.outgoing_open_cents == 5000

        tx = governance_v2.get_finance_taxonomy()
        enc = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=proj_fd,
                amount_cents=4000,
                fund_code="general_unrestricted",
                expense_kind=tx.expense_kinds[0].key,
                happened_at_utc="2026-03-16T19:00:00Z",
                request_id="req-ops-float-encumber",
            )
        )
        db.session.flush()

        assert alloc.ops_float_ulid
        assert enc.encumbrance_ulid

        demand = db.session.get(FundingDemand, proj_fd)
        assert demand is not None
        assert demand.status == "funding_in_progress"


def test_ops_float_bridge_is_auto_allowed(app):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)

        proj_fd = _create_published_demand(
            project_title="Elks Welcome Home",
            demand_title="Elks WHK Reimbursement Project",
            spending_class="basic_needs",
            source_profile_key="ops_bridge_preapproved",
            ops_support_planned=True,
        )

        out = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_code="general_unrestricted",
                amount_cents=3000,
                support_mode="bridge",
                request_id="req-ops-float-bridge-ok",
            )
        )
        db.session.flush()

        summary = finance_v2.get_ops_float_summary(proj_fd)
        assert out.ops_float_ulid
        assert summary.incoming_open_cents == 3000


def test_ops_float_repay_reduces_open_balance(app):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)

        proj_fd = _create_published_demand(
            project_title="Bridge Reimbursement",
            demand_title="Bridge Reimbursement Project",
        )

        alloc = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_code="general_unrestricted",
                amount_cents=5000,
                support_mode="bridge",
                request_id="req-ops-float-repay-alloc",
            )
        )
        db.session.flush()

        _realize_into_demand(proj_fd, 3000)

        repay = calendar_v2.repay_ops_float_to_operations(
            calendar_v2.OpsFloatSettlementRequestDTO(
                parent_ops_float_ulid=alloc.ops_float_ulid,
                amount_cents=2000,
                request_id="req-ops-float-repay",
            )
        )
        db.session.flush()

        summary_dest = finance_v2.get_ops_float_summary(proj_fd)
        summary_src = finance_v2.get_ops_float_summary(ops_fd)
        parent = finance_v2.get_ops_float(alloc.ops_float_ulid)

        assert repay.action == "repay"
        assert repay.ops_float_ulid
        assert parent.open_cents == 3000
        assert summary_dest.incoming_open_cents == 3000
        assert summary_src.outgoing_open_cents == 3000


def test_ops_float_forgive_requires_closed_project_and_governor(app):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)

        proj_fd = _create_published_demand(
            project_title="Elks Welcome Home",
            demand_title="Elks WHK Reimbursement Project",
            spending_class="basic_needs",
            source_profile_key="ops_bridge_preapproved",
            ops_support_planned=True,
        )

        alloc = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_code="general_unrestricted",
                amount_cents=4000,
                support_mode="seed",
                actor_domain_roles=("governor",),
                request_id="req-ops-float-forgive-alloc",
            )
        )
        db.session.flush()

        with pytest.raises(Exception) as exc:
            calendar_v2.forgive_ops_float_shortfall(
                calendar_v2.OpsFloatSettlementRequestDTO(
                    parent_ops_float_ulid=alloc.ops_float_ulid,
                    amount_cents=1000,
                    request_id="req-ops-float-forgive-open",
                )
            )
        assert "closed" in str(exc.value).lower()

        demand = db.session.get(FundingDemand, proj_fd)
        assert demand is not None
        demand.status = "closed"
        db.session.flush()

        with pytest.raises(Exception) as exc:
            calendar_v2.forgive_ops_float_shortfall(
                calendar_v2.OpsFloatSettlementRequestDTO(
                    parent_ops_float_ulid=alloc.ops_float_ulid,
                    amount_cents=1000,
                    request_id="req-ops-float-forgive-denied",
                )
            )
        msg = str(exc.value).lower()
        assert "approval" in msg or "permission" in msg

        forgive = calendar_v2.forgive_ops_float_shortfall(
            calendar_v2.OpsFloatSettlementRequestDTO(
                parent_ops_float_ulid=alloc.ops_float_ulid,
                amount_cents=1000,
                actor_domain_roles=("governor",),
                request_id="req-ops-float-forgive-ok",
            )
        )
        db.session.flush()

        summary_dest = finance_v2.get_ops_float_summary(proj_fd)
        summary_src = finance_v2.get_ops_float_summary(ops_fd)
        parent = finance_v2.get_ops_float(alloc.ops_float_ulid)

        assert forgive.action == "forgive"
        assert parent.open_cents == 3000
        assert summary_dest.incoming_open_cents == 3000
        assert summary_src.outgoing_open_cents == 3000
