# tests/slices/calendar/test_calendar_finance_bridge.py

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

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
from app.slices.finance.models import Encumbrance, Journal
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.ledger.models import LedgerEvent
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_funding import create_funding_intent


def _pick_approval_free_fund(eligible_fund_keys: tuple[str, ...]) -> str:
    if "general_unrestricted" in eligible_fund_keys:
        return "general_unrestricted"
    return eligible_fund_keys[0]


def _derive_restriction_type(
    restriction_keys: tuple[str, ...],
    archetype: str,
) -> str:
    keys = {str(k).strip().lower() for k in restriction_keys}
    arch = (archetype or "").strip().lower()

    if {"perm", "permanent", "permanently_restricted"} & keys or arch in {
        "perm",
        "permanent",
        "permanently_restricted",
    }:
        return "permanently_restricted"
    if {"temp", "temporary", "temporarily_restricted"} & keys or arch in {
        "temp",
        "temporary",
        "temporarily_restricted",
    }:
        return "temporarily_restricted"
    return "unrestricted"


def _seed_reserve_for_fund(
    *,
    funding_demand_ulid: str,
    fund_key: str,
    amount_cents: int,
) -> None:
    demand = calendar_v2.get_funding_demand(funding_demand_ulid)
    fund_meta = governance_v2.get_fund_key(fund_key)
    restriction_keys = governance_v2.apply_fund_defaults(
        fund_key=fund_key,
        restriction_keys=(),
    )
    fund_restriction_type = _derive_restriction_type(
        restriction_keys,
        fund_meta.archetype,
    )

    finance_v2.reserve_funds(
        finance_v2.ReserveRequestDTO(
            funding_demand_ulid=funding_demand_ulid,
            fund_key=fund_key,
            amount_cents=amount_cents,
            source="tests",
            fund_label=fund_meta.label,
            fund_restriction_type=fund_restriction_type,
            project_ulid=demand.project_ulid,
            source_ref_ulid=None,
            memo="seed reserve for approval test",
            actor_ulid=None,
            request_id="req-seed-restricted-reserve",
            dry_run=False,
        )
    )
    db.session.flush()


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


def _create_realized_demand() -> tuple[str, str]:
    project = Project(
        project_title="Calendar Finance Bridge",
        status="planned",
    )
    db.session.add(project)
    db.session.flush()

    demand = create_funding_demand(
        {
            "project_ulid": project.ulid,
            "title": "Bridge Demand",
            "goal_cents": 12000,
            "deadline_date": "2026-03-31",
            "spending_class": "admin",
            "tag_any": "",
        },
        actor_ulid=None,
        request_id="req-demand-create-2",
    )
    db.session.flush()

    demand = publish_funding_demand(
        demand.ulid,
        actor_ulid=None,
        request_id="req-demand-publish-2",
    )
    db.session.flush()

    sponsor = _create_sponsor("Bridge Sponsor")
    intent = create_funding_intent(
        {
            "sponsor_entity_ulid": sponsor.entity_ulid,
            "funding_demand_ulid": demand.ulid,
            "intent_kind": "donation",
            "amount_cents": 12000,
            "status": "committed",
            "note": "bridge receipt",
        },
        actor_ulid=None,
        request_id="req-intent-bridge",
    )
    db.session.flush()

    tx = governance_v2.get_finance_taxonomy()
    income_kind = tx.income_kinds[0].key
    fund_key = _pick_approval_free_fund(
        calendar_v2.get_funding_demand(demand.ulid).eligible_fund_keys
    )

    sponsors_v2.realize_funding_intent(
        sponsors_v2.FundingRealizationRequestDTO(
            intent_ulid=intent.ulid,
            amount_cents=12000,
            happened_at_utc="2026-03-16T10:00:00Z",
            fund_key=fund_key,
            income_kind=income_kind,
            receipt_method="bank",
            reserve_on_receive=True,
            request_id="req-realize-bridge",
        )
    )
    db.session.flush()
    return demand.ulid, fund_key


def test_encumber_project_funds_happy_path(app):
    with app.app_context():
        ensure_default_accounts()
        demand_ulid, fund_key = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[12].key

        out = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=8000,
                fund_key=fund_key,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T11:00:00Z",
                request_id="req-encumber-1",
            )
        )
        db.session.flush()

        demand = db.session.get(FundingDemand, demand_ulid)
        assert demand is not None
        assert demand.status == "funding_in_progress"

        enc = db.session.get(Encumbrance, out.encumbrance_ulid)
        assert enc is not None
        assert enc.funding_demand_ulid == demand_ulid
        assert enc.amount_cents == 8000
        assert enc.status == "active"
        assert out.decision_fingerprint

        money = finance_v2.get_funding_demand_money_view(demand_ulid)
        assert money.reserved_cents == 12000
        assert money.encumbered_cents == 8000

        evt = (
            db.session.execute(
                select(LedgerEvent).where(
                    LedgerEvent.event_type
                    == "calendar.project_funds_encumbered",
                    LedgerEvent.target_ulid == demand_ulid,
                )
            )
            .scalars()
            .one_or_none()
        )
        assert evt is not None


def test_spend_project_funds_happy_path(app):
    with app.app_context():
        ensure_default_accounts()
        demand_ulid, fund_key = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        enc = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=8000,
                fund_key=fund_key,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T11:30:00Z",
                request_id="req-encumber-2",
            )
        )
        db.session.flush()

        out = calendar_v2.spend_project_funds(
            calendar_v2.ProjectSpendRequestDTO(
                encumbrance_ulid=enc.encumbrance_ulid,
                amount_cents=3000,
                expense_kind=expense_kind,
                payment_method="bank",
                happened_at_utc="2026-03-16T12:00:00Z",
                request_id="req-spend-1",
            )
        )
        db.session.flush()

        demand = db.session.get(FundingDemand, demand_ulid)
        assert demand is not None
        assert demand.status == "executing"

        journal = db.session.get(Journal, out.journal_ulid)
        assert journal is not None
        assert journal.funding_demand_ulid == demand_ulid

        enc_row = db.session.get(Encumbrance, enc.encumbrance_ulid)
        assert enc_row is not None
        assert enc_row.relieved_cents == 3000
        assert enc_row.status == "active"

        money = finance_v2.get_funding_demand_money_view(demand_ulid)
        assert money.encumbered_cents == 5000
        assert money.spent_cents == 3000

        evt = (
            db.session.execute(
                select(LedgerEvent).where(
                    LedgerEvent.event_type == "calendar.project_funds_spent",
                    LedgerEvent.target_ulid == demand_ulid,
                )
            )
            .scalars()
            .one_or_none()
        )
        assert evt is not None


def test_encumber_rejects_when_over_reserved(app):
    with app.app_context():
        ensure_default_accounts()
        demand_ulid, fund_key = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        with pytest.raises(Exception) as exc:
            calendar_v2.encumber_project_funds(
                calendar_v2.ProjectEncumbranceRequestDTO(
                    funding_demand_ulid=demand_ulid,
                    amount_cents=13000,
                    fund_key=fund_key,
                    expense_kind=expense_kind,
                    happened_at_utc="2026-03-16T13:00:00Z",
                    request_id="req-encumber-over",
                )
            )

        assert "reserved" in str(exc.value).lower()


def test_spend_rejects_when_over_open_encumbrance(app):
    with app.app_context():
        ensure_default_accounts()
        demand_ulid, fund_key = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        enc = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=4000,
                fund_key=fund_key,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T11:45:00Z",
                request_id="req-encumber-3",
            )
        )
        db.session.flush()

        with pytest.raises(Exception) as exc:
            calendar_v2.spend_project_funds(
                calendar_v2.ProjectSpendRequestDTO(
                    encumbrance_ulid=enc.encumbrance_ulid,
                    amount_cents=5000,
                    expense_kind=expense_kind,
                    payment_method="bank",
                    happened_at_utc="2026-03-16T14:00:00Z",
                    request_id="req-spend-over",
                )
            )

        assert "encumbered" in str(exc.value).lower()


def test_encumber_rejects_when_selected_fund_requires_approval(app):
    with app.app_context():
        ensure_default_accounts()
        demand_ulid, _ = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        demand = calendar_v2.get_funding_demand(demand_ulid)
        restricted = None
        for key in demand.eligible_fund_keys:
            if key == "general_restricted":
                restricted = key
                break

        if restricted is None:
            pytest.skip("no approval-requiring restricted fund eligible")

        _seed_reserve_for_fund(
            funding_demand_ulid=demand_ulid,
            fund_key=restricted,
            amount_cents=12000,
        )

        with pytest.raises(Exception) as exc:
            calendar_v2.encumber_project_funds(
                calendar_v2.ProjectEncumbranceRequestDTO(
                    funding_demand_ulid=demand_ulid,
                    amount_cents=8000,
                    fund_key=restricted,
                    expense_kind=expense_kind,
                    happened_at_utc="2026-03-16T15:00:00Z",
                    request_id="req-encumber-restricted",
                )
            )

        msg = str(exc.value).lower()
        assert "approval" in msg or "permission" in msg


def test_encumber_project_funds_forwards_source_profile_hint(
    app, monkeypatch
):
    from app.slices.calendar import services_funding as funding_svc

    captured: dict[str, object] = {}

    def fake_hints(project_ulid: str) -> ProjectPolicyHints:
        return ProjectPolicyHints(
            source_profile_key="restricted_project_grant_return_unused",
            ops_support_planned=None,
        )

    def fake_preview(req):
        captured["source_profile_key"] = req.source_profile_key
        return SimpleNamespace(
            allowed=True,
            required_approvals=(),
            reason_codes=(),
            decision_fingerprint="fp-encumber",
        )

    with app.app_context():
        ensure_default_accounts()
        demand_ulid, fund_key = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        monkeypatch.setattr(
            funding_svc,
            "_project_policy_hints",
            fake_hints,
        )
        monkeypatch.setattr(
            governance_v2,
            "preview_funding_decision",
            fake_preview,
        )

        out = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=4000,
                fund_key=fund_key,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T20:00:00Z",
                request_id="req-encumber-source-profile",
            )
        )
        db.session.flush()

        assert out.encumbrance_ulid
        assert (
            captured["source_profile_key"]
            == "restricted_project_grant_return_unused"
        )
