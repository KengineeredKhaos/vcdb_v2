from __future__ import annotations

from app.extensions import db
from app.slices.finance import services_grants
from app.slices.finance.models import Grant
from app.slices.finance.services_journal import ensure_default_accounts, ensure_fund


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


def test_submit_reimbursement_uses_grant_project_default(app, ulid):
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
                "award_name": "Small Grant",
                "amount_awarded_cents": 10000,
                "start_on": "2026-01-01",
                "end_on": "2026-12-31",
                "reporting_frequency": "annual",
            }
        )
        db.session.flush()

        claim = services_grants.submit_reimbursement(
            {
                "grant_ulid": grant["id"],
                "submitted_on": "2026-03-01",
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "claimed_amount_cents": 2500,
                "status": "submitted",
            }
        )
        assert claim["project_ulid"] == grant["project_ulid"]
        assert claim["claimed_amount_cents"] == 2500
