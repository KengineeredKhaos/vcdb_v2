from sqlalchemy import select

from app.extensions import db
from app.slices.finance.models import Account, Fund, Journal, JournalLine
from app.slices.finance.services_report import statement_of_activities


def test_statement_of_activities_groups_by_project_ulid_without_shadow_project(
    app, ulid
):
    with app.app_context():
        fund_code = f"cleanup_{ulid().lower()[-8:]}"

        fund = Fund(
            code=fund_code,
            name="Cleanup Fund",
            restriction="unrestricted",
            active=True,
        )
        db.session.add(fund)

        asset_acct = db.session.execute(
            select(Account)
            .where(Account.type == "asset", Account.active.is_(True))
            .order_by(Account.code.asc())
            .limit(1)
        ).scalar_one()

        revenue_acct = db.session.execute(
            select(Account)
            .where(Account.type == "revenue", Account.active.is_(True))
            .order_by(Account.code.asc())
            .limit(1)
        ).scalar_one()

        db.session.flush()

        p1 = ulid()
        p2 = ulid()

        j1 = Journal(
            source="test",
            funding_demand_ulid=ulid(),
            period_key="2026-04",
            happened_at_utc="2026-04-01T00:00:00Z",
        )
        db.session.add(j1)
        db.session.flush()
        db.session.add_all(
            [
                JournalLine(
                    journal_ulid=j1.ulid,
                    funding_demand_ulid=j1.funding_demand_ulid,
                    seq=1,
                    account_code=asset_acct.code,
                    fund_code=fund.code,
                    project_ulid=p1,
                    amount_cents=1000,
                    period_key="2026-04",
                ),
                JournalLine(
                    journal_ulid=j1.ulid,
                    funding_demand_ulid=j1.funding_demand_ulid,
                    seq=2,
                    account_code=revenue_acct.code,
                    fund_code=fund.code,
                    project_ulid=p1,
                    amount_cents=-1000,
                    period_key="2026-04",
                ),
            ]
        )

        j2 = Journal(
            source="test",
            funding_demand_ulid=ulid(),
            period_key="2026-04",
            happened_at_utc="2026-04-02T00:00:00Z",
        )
        db.session.add(j2)
        db.session.flush()
        db.session.add_all(
            [
                JournalLine(
                    journal_ulid=j2.ulid,
                    funding_demand_ulid=j2.funding_demand_ulid,
                    seq=1,
                    account_code=asset_acct.code,
                    fund_code=fund.code,
                    project_ulid=p2,
                    amount_cents=2000,
                    period_key="2026-04",
                ),
                JournalLine(
                    journal_ulid=j2.ulid,
                    funding_demand_ulid=j2.funding_demand_ulid,
                    seq=2,
                    account_code=revenue_acct.code,
                    fund_code=fund.code,
                    project_ulid=p2,
                    amount_cents=-2000,
                    period_key="2026-04",
                ),
            ]
        )
        db.session.commit()

        report = statement_of_activities("2026-04")
        by_project = report["by_project"]

        assert p1 in by_project
        assert p2 in by_project
        assert by_project[p1]["revenue_cents"] == 1000
        assert by_project[p2]["revenue_cents"] == 2000
