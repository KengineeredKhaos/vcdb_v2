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
from app.slices.calendar.services_funding import (
    create_funding_demand,
    publish_funding_demand,
)
from app.slices.entity.models import Entity, EntityOrg
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_funding import create_funding_intent


def _patch_publishable_hints(
    monkeypatch,
    *,
    source_profile_key="restricted_project_grant_return_unused",
    ops_support_planned=False,
):
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key=source_profile_key,
            ops_support_planned=ops_support_planned,
        ),
    )


@pytest.fixture(autouse=True)
def _default_publishable_hints(monkeypatch):
    _patch_publishable_hints(monkeypatch)


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
    spending_class: str = "admin",
    goal_cents: int = 12000,
) -> str:
    project = Project(project_title=project_title, status="planned")
    db.session.add(project)
    db.session.flush()

    row = create_funding_demand(
        {
            "project_ulid": project.ulid,
            "title": demand_title,
            "goal_cents": goal_cents,
            "deadline_date": "2026-12-31",
            "spending_class": spending_class,
            "tag_any": "",
        },
        actor_ulid=None,
        request_id=f"req-{project_title}-create",
    )
    db.session.flush()
    row = publish_funding_demand(
        row.ulid,
        actor_ulid=None,
        request_id=f"req-{project_title}-publish",
    )
    db.session.flush()
    return row.ulid


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
            fund_key="general_unrestricted",
            income_kind=tx.income_kinds[0].key,
            receipt_method="bank",
            reserve_on_receive=True,
            request_id="req-ops-float-realize",
        )
    )
    db.session.flush()
    return out.journal_ulid


def test_ops_float_seed_requires_governor(app, monkeypatch):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)
        _patch_publishable_hints(
            monkeypatch,
            source_profile_key="ops_seed_board_motion",
            ops_support_planned=True,
        )
        proj_fd = _create_published_demand(
            project_title="Stand Down",
            demand_title="Stand Down 2026",
        )

        with pytest.raises(Exception) as exc:
            calendar_v2.allocate_ops_float_to_project(
                calendar_v2.OpsFloatAllocationRequestDTO(
                    source_funding_demand_ulid=ops_fd,
                    dest_funding_demand_ulid=proj_fd,
                    fund_key="general_unrestricted",
                    amount_cents=5000,
                    support_mode="seed",
                    request_id="req-ops-float-seed-denied",
                )
            )

        msg = str(exc.value).lower()
        assert "approval" in msg or "permission" in msg


def test_ops_float_seed_allocation_enables_project_encumber(app, monkeypatch):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)
        _patch_publishable_hints(
            monkeypatch,
            source_profile_key="ops_seed_board_motion",
            ops_support_planned=True,
        )
        proj_fd = _create_published_demand(
            project_title="Welcome Home Kits",
            demand_title="Welcome Home Kit Project",
        )

        alloc = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_key="general_unrestricted",
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
                fund_key="general_unrestricted",
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


def test_ops_float_bridge_is_auto_allowed(app, monkeypatch):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)
        _patch_publishable_hints(
            monkeypatch,
            source_profile_key="ops_bridge_preapproved",
            ops_support_planned=True,
        )
        proj_fd = _create_published_demand(
            project_title="Elks Welcome Home",
            demand_title="Elks WHK Reimbursement Project",
            spending_class="basic_needs",
        )

        out = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_key="general_unrestricted",
                amount_cents=3000,
                support_mode="bridge",
                request_id="req-ops-float-bridge-ok",
            )
        )
        db.session.flush()

        summary = finance_v2.get_ops_float_summary(proj_fd)
        assert out.ops_float_ulid
        assert summary.incoming_open_cents == 3000


def test_ops_float_repay_reduces_open_balance(app, monkeypatch):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)
        _patch_publishable_hints(
            monkeypatch,
            source_profile_key="welcome_home_reimbursement_bridgeable",
            ops_support_planned=True,
        )
        proj_fd = _create_published_demand(
            project_title="Bridge Reimbursement",
            demand_title="Bridge Reimbursement Project",
        )

        alloc = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_key="general_unrestricted",
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


def test_ops_float_forgive_requires_closed_project_and_governor(
    app, monkeypatch
):
    with app.app_context():
        ensure_default_accounts()
        ops_fd = _create_published_demand(
            project_title="Operations",
            demand_title="General Operations 2026",
        )
        _realize_into_demand(ops_fd, 12000)
        _patch_publishable_hints(
            monkeypatch,
            source_profile_key="ops_seed_board_motion",
            ops_support_planned=True,
        )
        proj_fd = _create_published_demand(
            project_title="Unreimbursed Shortfall",
            demand_title="Unreimbursed Shortfall Project",
        )

        alloc = calendar_v2.allocate_ops_float_to_project(
            calendar_v2.OpsFloatAllocationRequestDTO(
                source_funding_demand_ulid=ops_fd,
                dest_funding_demand_ulid=proj_fd,
                fund_key="general_unrestricted",
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
