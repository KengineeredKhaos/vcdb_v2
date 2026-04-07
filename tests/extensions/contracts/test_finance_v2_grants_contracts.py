from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import finance_v2
from app.extensions.errors import ContractError
from app.slices.finance.models import Disbursement, Grant
from app.slices.finance.services_journal import (
    ensure_default_accounts,
    ensure_fund,
    post_journal,
)


def test_create_grant_award_persists_richer_grant_fields(app, ulid):
    with app.app_context():
        ensure_default_accounts()
        fund = ensure_fund(
            code="welcome_home_elks",
            name="Welcome Home Elks",
            restriction="temporarily_restricted",
        )

        out = finance_v2.create_grant_award(
            {
                "sponsor_ulid": ulid(),
                "award_name": "Welcome Home Grant",
                "award_number": "ELKS-2026-01",
                "amount_awarded_cents": 40000,
                "fund_code": fund.code,
                "restriction_type": "temporarily_restricted",
                "funding_mode": "reimbursement",
                "reporting_frequency": "end_of_term",
                "start_on": "2026-04-01",
                "end_on": "2026-05-31",
                "project_ulid": ulid(),
                "allowable_expense_kinds": [
                    "food",
                    "housewares",
                    "food",
                ],
                "match_required_cents": 0,
                "program_income_allowed": False,
                "conditions_summary": "Up to $400 per client kit.",
                "source_document_ref": "award-letter.pdf",
                "notes": "local pilot",
                "status": "active",
                "request_id": "req-grant-create",
            }
        )
        db.session.flush()

        row = db.session.get(Grant, out["id"])
        assert row is not None
        assert row.fund_code == fund.code
        assert row.restriction_type == "temporarily_restricted"
        assert row.award_name == "Welcome Home Grant"
        assert row.funding_mode == "reimbursement"
        assert row.reporting_frequency == "end_of_term"
        assert row.allowable_expense_kinds == ["food", "housewares"]
        assert out["allowable_expense_kinds"] == ("food", "housewares")


def test_create_grant_award_rejects_bad_payload_shape(app):
    with app.app_context():
        with pytest.raises(ContractError) as exc:
            finance_v2.create_grant_award(["not", "a", "dict"])  # type: ignore[arg-type]
        assert exc.value.code == "bad_argument"


def test_record_disbursement_writes_cash_out_row(app, ulid):
    with app.app_context():
        ensure_default_accounts()
        fund = ensure_fund(
            code="general_unrestricted",
            name="General Unrestricted",
            restriction="unrestricted",
        )

        project_ulid = ulid()
        funding_demand_ulid = ulid()
        expense_journal_ulid = post_journal(
            source="tests",
            external_ref_ulid=None,
            happened_at_utc="2026-04-01T12:00:00Z",
            currency="USD",
            memo="expense for disbursement test",
            created_by_actor=None,
            lines=[
                {
                    "account_code": "5100",
                    "fund_code": fund.code,
                    "funding_demand_ulid": funding_demand_ulid,
                    "project_ulid": project_ulid,
                    "amount_cents": 1500,
                    "memo": "supplies debit",
                },
                {
                    "account_code": "1000",
                    "fund_code": fund.code,
                    "funding_demand_ulid": funding_demand_ulid,
                    "project_ulid": project_ulid,
                    "amount_cents": -1500,
                    "memo": "cash credit",
                },
            ],
        )

        out = finance_v2.record_disbursement(
            {
                "expense_journal_ulid": expense_journal_ulid,
                "grant_ulid": None,
                "project_ulid": project_ulid,
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": 1500,
                "disbursed_on": "2026-04-02",
                "method": "check",
                "reference": "CHK-1001",
                "status": "recorded",
                "request_id": "req-disb-1",
            }
        )
        db.session.flush()

        row = db.session.get(Disbursement, out["id"])
        assert row is not None
        assert row.expense_journal_ulid == expense_journal_ulid
        assert row.project_ulid == project_ulid
        assert row.funding_demand_ulid == funding_demand_ulid
        assert row.amount_cents == 1500
        assert row.method == "check"

        all_rows = db.session.execute(select(Disbursement)).scalars().all()
        assert len(all_rows) == 1


def test_record_disbursement_rejects_missing_journal(app, ulid):
    with app.app_context():
        with pytest.raises(ContractError) as exc:
            finance_v2.record_disbursement(
                {
                    "expense_journal_ulid": ulid(),
                    "project_ulid": ulid(),
                    "amount_cents": 500,
                    "disbursed_on": "2026-04-02",
                    "method": "ach",
                }
            )
        assert exc.value.code == "not_found"
