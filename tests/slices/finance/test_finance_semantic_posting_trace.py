# /tests/slices/finance/test_finance_semantic_posting_trace.py
from __future__ import annotations

from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import finance_v2, governance_v2
from app.slices.finance.models import Journal, JournalLine
from app.slices.finance.services_journal import ensure_default_accounts


def test_post_income_writes_funding_demand_trace(app, ulid):
    with app.app_context():
        ensure_default_accounts()

        tx = governance_v2.get_finance_taxonomy()
        fund_key = tx.fund_keys[0].key
        fund_label = tx.fund_keys[0].label
        income_kind = tx.income_kinds[0].key

        funding_demand_ulid = ulid()
        project_ulid = ulid()

        out = finance_v2.post_income(
            finance_v2.IncomePostRequestDTO(
                amount_cents=2500,
                happened_at_utc="2026-03-15T12:00:00Z",
                fund_key=fund_key,
                fund_label=fund_label,
                fund_restriction_type="unrestricted",
                income_kind=income_kind,
                receipt_method="bank",
                source="tests",
                funding_demand_ulid=funding_demand_ulid,
                project_ulid=project_ulid,
                payer_entity_ulid=ulid(),
                memo="semantic income trace test",
                created_by_actor=None,
            )
        )

        journal = db.session.get(Journal, out.id)
        assert journal is not None
        assert journal.funding_demand_ulid == funding_demand_ulid

        lines = (
            db.session.execute(
                select(JournalLine).where(JournalLine.journal_ulid == out.id)
            )
            .scalars()
            .all()
        )

        assert len(lines) == 2
        assert {line.funding_demand_ulid for line in lines} == {
            funding_demand_ulid
        }
        assert {line.project_ulid for line in lines} == {project_ulid}
