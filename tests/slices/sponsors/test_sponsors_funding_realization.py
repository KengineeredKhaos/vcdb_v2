# tests/slices/sponsors/test_sponsors_funding_realization.py

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import calendar_v2, governance_v2, sponsors_v2
from app.slices.calendar.models import Project
from app.slices.calendar.services_funding import (
    create_funding_demand,
    publish_funding_demand,
)
from app.slices.entity.models import Entity, EntityOrg
from app.slices.finance.models import Journal, Reserve
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.ledger.models import LedgerEvent
from app.slices.sponsors.models import Sponsor, SponsorFundingIntent
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


def _create_published_demand() -> str:
    project = Project(
        project_title="Bridge Test Project",
        status="planned",
    )
    db.session.add(project)
    db.session.flush()

    row = create_funding_demand(
        {
            "project_ulid": project.ulid,
            "title": "Bridge Test Demand",
            "goal_cents": 12000,
            "deadline_date": "2026-03-31",
            "spending_class": "admin",
            "tag_any": "",
        },
        actor_ulid=None,
        request_id="req-demand-create",
    )
    db.session.flush()

    row = publish_funding_demand(
        row.ulid,
        actor_ulid=None,
        request_id="req-demand-publish",
    )
    db.session.flush()
    return row.ulid


def test_realize_funding_intent_posts_income_and_reserve(app):
    with app.app_context():
        ensure_default_accounts()

        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Sponsor Realization Test")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "donation",
                "amount_cents": 12000,
                "status": "committed",
                "note": "earmarked receipt",
            },
            actor_ulid=None,
            request_id="req-intent-create",
        )
        db.session.flush()

        demand = sponsors_v2.get_funding_intent_totals(demand_ulid)
        assert demand.pledged_cents == 12000

        funding_demand = calendar_v2.get_funding_demand(demand_ulid)
        assert funding_demand.eligible_fund_keys

        tx = governance_v2.get_finance_taxonomy()
        fund_key = funding_demand.eligible_fund_keys[0]
        income_kind = tx.income_kinds[0].key

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=12000,
                happened_at_utc="2026-03-15T14:00:00Z",
                fund_key=fund_key,
                income_kind=income_kind,
                receipt_method="bank",
                reserve_on_receive=True,
                memo="realization bridge test",
                actor_ulid=None,
                request_id="req-realize-1",
            )
        )
        db.session.flush()
        
        refreshed = db.session.get(SponsorFundingIntent, intent.ulid)

        assert refreshed is not None
        assert refreshed.status == "fulfilled"
        assert out.status == "fulfilled"

        journal = db.session.get(Journal, out.journal_ulid)
        assert journal is not None
        assert journal.funding_demand_ulid == demand_ulid

        reserve = db.session.get(Reserve, out.reserve_ulid)
        assert reserve is not None
        assert reserve.funding_demand_ulid == demand_ulid
        assert reserve.amount_cents == 12000

        ledger_row = (
            db.session.execute(
                select(LedgerEvent).where(
                    LedgerEvent.target_ulid == intent.ulid,
                    LedgerEvent.event_type
                    == "sponsors.sponsor_funding_realized",
                )
            )
            .scalars()
            .one_or_none()
        )
        assert ledger_row is not None


def test_realize_funding_intent_rejects_non_committed(app):
    with app.app_context():
        ensure_default_accounts()

        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Sponsor Draft Intent")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "donation",
                "amount_cents": 5000,
                "status": "draft",
                "note": None,
            },
            actor_ulid=None,
            request_id="req-intent-draft",
        )
        db.session.flush()


        funding_demand = calendar_v2.get_funding_demand(demand_ulid)
        tx = governance_v2.get_finance_taxonomy()

        with pytest.raises(Exception) as exc:
            sponsors_v2.realize_funding_intent(
                sponsors_v2.FundingRealizationRequestDTO(
                    intent_ulid=intent.ulid,
                    amount_cents=5000,
                    happened_at_utc="2026-03-15T15:00:00Z",
                    fund_key=funding_demand.eligible_fund_keys[0],
                    income_kind=tx.income_kinds[0].key,
                    receipt_method="bank",
                    request_id="req-realize-draft",
                )
            )

        assert "committed" in str(exc.value).lower()
