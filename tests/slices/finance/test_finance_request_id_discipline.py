from __future__ import annotations

from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import finance_v2, governance_v2
from app.lib.request_ctx import use_request_ctx
from app.slices.finance.models import FinancePostingFact
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.ledger.models import LedgerEvent


def test_post_income_uses_explicit_request_id_for_fact_and_ledger(app, ulid):
    with app.app_context():
        ensure_default_accounts()

        tx = governance_v2.get_finance_taxonomy()
        fund_code = tx.fund_codes[0].key
        fund_label = tx.fund_codes[0].label
        income_kind = tx.income_kinds[0].key
        request_id = ulid()

        out = finance_v2.post_income(
            finance_v2.IncomePostRequestDTO(
                amount_cents=2500,
                happened_at_utc="2026-03-15T12:00:00Z",
                fund_code=fund_code,
                fund_label=fund_label,
                fund_restriction_type="unrestricted",
                income_kind=income_kind,
                receipt_method="bank",
                source="tests",
                funding_demand_ulid=ulid(),
                project_ulid=ulid(),
                payer_entity_ulid=ulid(),
                memo="request id discipline test",
                created_by_actor=None,
                request_id=request_id,
            )
        )

        fact = db.session.execute(
            select(FinancePostingFact).where(
                FinancePostingFact.journal_ulid == out.id
            )
        ).scalar_one()
        assert fact.request_id == request_id

        event = db.session.execute(
            select(LedgerEvent).where(
                LedgerEvent.target_ulid == out.id,
                LedgerEvent.operation == "income_posted",
            )
        ).scalar_one()
        assert event.request_id == request_id


def test_reserve_funds_falls_back_to_request_ctx_request_id(app, ulid):
    with app.app_context():
        ensure_default_accounts()
        request_id = ulid()

        with use_request_ctx(request_id):
            out = finance_v2.reserve_funds(
                finance_v2.ReserveRequestDTO(
                    funding_demand_ulid=ulid(),
                    project_ulid=ulid(),
                    fund_code="general_unrestricted",
                    amount_cents=1200,
                    source="tests",
                    fund_label="General",
                    fund_restriction_type="unrestricted",
                    memo="ctx request id fallback test",
                    actor_ulid=None,
                )
            )

        event = db.session.execute(
            select(LedgerEvent).where(
                LedgerEvent.target_ulid == out.id,
                LedgerEvent.operation == "reserve_recorded",
            )
        ).scalar_one()
        assert event.request_id == request_id
