from __future__ import annotations

from app.extensions import db
from app.slices.finance import services_grants
from app.slices.finance.models import Encumbrance, Grant, Reserve
from app.slices.finance.services_journal import (
    ensure_default_accounts,
    ensure_fund,
)
from app.slices.finance.services_semantic_posting import (
    post_expense,
    post_income,
)


def test_create_grant_and_prepare_report_empty(app, ulid):
    with app.app_context():
        ensure_default_accounts()
        ensure_fund(
            code="general_unrestricted",
            name="General",
            restriction="unrestricted",
        )

        grant = services_grants.create_grant(
            {
                "fund_code": "general_unrestricted",
                "restriction_type": "unrestricted",
                "sponsor_ulid": ulid(),
                "project_ulid": ulid(),
                "award_number": "ELKS-2026-1",
                "award_name": "Welcome Home Grant",
                "funding_mode": "reimbursement",
                "amount_awarded_cents": 40000,
                "start_on": "2026-01-01",
                "end_on": "2026-12-31",
                "reporting_frequency": "end_of_term",
                "allowable_expense_kinds": ["food", "housewares"],
                "program_income_allowed": False,
                "status": "active",
            }
        )
        db.session.flush()

        row = db.session.get(Grant, grant["id"])
        assert row is not None
        assert row.project_ulid == grant["project_ulid"]
        assert row.allowable_expense_kinds == ["food", "housewares"]

        report = services_grants.prepare_grant_report(
            {
                "grant_ulid": grant["id"],
                "period_start": "2026-01-01",
                "period_end": "2026-12-31",
            }
        )
        assert report["grant"]["award_name"] == "Welcome Home Grant"
        assert report["funding"]["amount_awarded_cents"] == 40000
        assert report["commitments"]["reserved_cents"] == 0
        assert report["spending"]["posted_expense_cents"] == 0


def test_prepare_grant_report_rolls_up_finance_truth(app, ulid):
    with app.app_context():
        ensure_default_accounts()
        ensure_fund(
            code="general_unrestricted",
            name="General",
            restriction="unrestricted",
        )

        funding_demand_ulid = ulid()
        project_ulid = ulid()
        sponsor_ulid = ulid()

        grant = services_grants.create_grant(
            {
                "fund_code": "general_unrestricted",
                "restriction_type": "unrestricted",
                "sponsor_ulid": sponsor_ulid,
                "project_ulid": project_ulid,
                "award_number": "ELKS-2026-2",
                "award_name": "Welcome Home Grant 2",
                "funding_mode": "reimbursement",
                "amount_awarded_cents": 40000,
                "start_on": "2026-01-01",
                "end_on": "2026-12-31",
                "reporting_frequency": "end_of_term",
                "status": "active",
            }
        )
        db.session.flush()

        income = post_income(
            {
                "amount_cents": 15000,
                "happened_at_utc": "2026-02-01T12:00:00Z",
                "fund_code": "general_unrestricted",
                "fund_label": "General",
                "fund_restriction_type": "unrestricted",
                "income_kind": "grant_disbursement",
                "receipt_method": "bank",
                "source": "tests",
                "funding_demand_ulid": funding_demand_ulid,
                "project_ulid": project_ulid,
                "memo": "grant income",
                "grant_ulid": grant["id"],
            }
        )
        expense = post_expense(
            {
                "amount_cents": 3000,
                "happened_at_utc": "2026-02-10T12:00:00Z",
                "fund_code": "general_unrestricted",
                "fund_label": "General",
                "fund_restriction_type": "unrestricted",
                "expense_kind": "event_food",
                "payment_method": "bank",
                "source": "tests",
                "funding_demand_ulid": funding_demand_ulid,
                "project_ulid": project_ulid,
                "memo": "grant expense",
                "grant_ulid": grant["id"],
            }
        )

        reserve = Reserve(
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=project_ulid,
            grant_ulid=grant["id"],
            fund_code="general_unrestricted",
            amount_cents=1000,
            status="active",
            source="tests",
            source_ref_ulid=income["id"],
        )
        enc = Encumbrance(
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=project_ulid,
            grant_ulid=grant["id"],
            fund_code="general_unrestricted",
            amount_cents=2500,
            relieved_cents=500,
            status="active",
            source="tests",
            source_ref_ulid=expense["id"],
        )
        db.session.add_all([reserve, enc])
        db.session.flush()

        claim = services_grants.submit_reimbursement(
            {
                "grant_ulid": grant["id"],
                "project_ulid": project_ulid,
                "funding_demand_ulid": funding_demand_ulid,
                "claim_number": "CLM-001",
                "submitted_on": "2026-02-20",
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "claimed_amount_cents": 3000,
                "approved_amount_cents": 2500,
                "received_amount_cents": 1000,
                "status": "approved",
            }
        )
        services_grants.record_disbursement(
            {
                "expense_journal_ulid": expense["id"],
                "grant_ulid": grant["id"],
                "project_ulid": project_ulid,
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": 2750,
                "disbursed_on": "2026-02-12",
                "method": "check",
                "reference": "CHK-001",
            }
        )
        db.session.commit()

        report = services_grants.prepare_grant_report(
            {
                "grant_ulid": grant["id"],
                "period_start": "2026-01-01",
                "period_end": "2026-12-31",
            }
        )

        assert report["funding"]["income_received_cents"] == 15000
        assert report["funding"]["remaining_authority_cents"] == 37000
        assert report["commitments"]["reserved_cents"] == 1000
        assert report["commitments"]["encumbered_open_cents"] == 2000
        assert report["commitments"]["encumbrance_relieved_cents"] == 500
        assert report["spending"]["posted_expense_cents"] == 3000
        assert report["spending"]["disbursed_cents"] == 2750
        assert report["reimbursements"]["claimed_cents"] == 3000
        assert report["reimbursements"]["approved_cents"] == 2500
        assert report["reimbursements"]["received_cents"] == 1000
        assert report["reimbursements"]["outstanding_cents"] == 1500
        assert claim["id"] in report["reimbursements"]["claim_ulids"]
        assert (
            expense["id"] in report["traceability"]["expense_journal_ulids"]
        )
        assert income["id"] in report["traceability"]["income_journal_ulids"]
        assert reserve.ulid in report["traceability"]["reserve_ulids"]
        assert enc.ulid in report["traceability"]["encumbrance_ulids"]
