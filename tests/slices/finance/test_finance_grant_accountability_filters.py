from __future__ import annotations

from app.extensions import db
from app.slices.finance import services_grants
from app.slices.finance.services_journal import ensure_default_accounts, ensure_fund


def test_grant_accountability_route_honors_period_filters(app, client, ulid):
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
                "award_number": "ELKS-2026-4",
                "award_name": "Filter Test Grant",
                "funding_mode": "reimbursement",
                "amount_awarded_cents": 40000,
                "start_on": "2026-01-01",
                "end_on": "2026-12-31",
                "reporting_frequency": "annual",
                "status": "active",
            }
        )
        db.session.commit()

    res = client.get(
        f"/finance/grants/{grant['id']}/accountability"
        "?start_on=2026-02-01&end_on=2026-02-28"
    )
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "Grant Accountability" in text
    assert "Filter Test Grant" in text
    assert "2026-02-01 to 2026-02-28" in text
