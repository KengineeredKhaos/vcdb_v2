# app/slices/finance/services_report.py
from __future__ import annotations

from sqlalchemy import text

from app.extensions import db

"""
Canonical Mental Model:
services_report → Reads from everything and summarizes.

TL;DR:
if it’s
    query-only
    returns summaries/aggregates
it belongs in services_report.

In future:
“Budget vs actuals by fund/project.”
“Sponsor utilization summaries.”
“Period summary metrics.”

I’d not move writers like record_stat_metric here;
they’re better in services_journal or a future services_stats.py.


"""

# NOTE: This is intentionally written using SQL text for portability across
# whatever model helpers you finalize later.
# It assumes the following minimal columns exist:
#   finance_journal (ulid, posted_at_utc, period_key)
#   finance_journal_line (
#       journal_ulid,
#       account_code,
#       fund_code,
#       project_code,
#       amount_cents,
#   )
#   finance_fund (ulid, name, restriction)
#   finance_project (ulid, name)
# Revenue accounts assumed to start with '4', expense with '5'
# (per your seed list).


def _sum_rows(rows) -> int:
    return int(sum(r["amount_cents"] or 0 for r in rows))


def statement_of_activities(period: str):
    # Aggregate by fund (join via ULID)
    q_fund = text(
        """
    SELECT
        f.ulid AS fund_id,
        COALESCE(f.name, '(unassigned)') AS fund_name,
        COALESCE(f.restriction, 'unrestricted') AS restriction_type,

        -- Revenue accounts are credits (negative) in the signed-cents scheme,
        -- so negate to present positive revenue.
        -SUM(CASE WHEN jl.account_code LIKE '4%' THEN jl.amount_cents ELSE 0 END)
            AS revenue_cents,

        -- Expenses are debits (positive). Include 5xxx and 6xxx.
        SUM(CASE
              WHEN jl.account_code LIKE '5%' OR jl.account_code LIKE '6%'
              THEN jl.amount_cents
              ELSE 0
            END) AS expense_cents

    FROM finance_journal j
    JOIN finance_journal_line jl ON jl.journal_ulid = j.ulid
    LEFT JOIN finance_fund f ON f.code = jl.fund_code
    WHERE j.period_key = :period
    GROUP BY f.code, f.name, f.restriction
    ORDER BY fund_name
    """
    )
    fund_rows = (
        db.session.execute(q_fund, {"period": period}).mappings().all()
    )

    # Aggregate by project (join via ULID)
    q_proj = text(
        """
        SELECT p.ulid AS project_id,
               COALESCE(p.name, '(unassigned)') AS project_name,
               SUM(CASE WHEN jl.account_code LIKE '4%' THEN jl.amount_cents ELSE 0 END) AS revenue_cents,
               SUM(CASE WHEN jl.account_code LIKE '5%' THEN jl.amount_cents ELSE 0 END) AS expense_cents
        FROM finance_journal j
        JOIN finance_journal_line jl ON jl.journal_ulid = j.ulid
        LEFT JOIN finance_project p ON p.ulid = jl.project_ulid
        WHERE j.period_key = :period
        GROUP BY p.ulid, p.name
    """
    )
    proj_rows = (
        db.session.execute(q_proj, {"period": period}).mappings().all()
    )

    by_restriction: dict[str, dict[str, int]] = {}
    for r in fund_rows:
        key = r["restriction_type"]
        bucket = by_restriction.setdefault(
            key,
            {
                "revenue_cents": 0,
                "expense_cents": 0,
                "change_net_assets_cents": 0,
            },
        )
        bucket["revenue_cents"] += int(r["revenue_cents"] or 0)
        bucket["expense_cents"] += int(r["expense_cents"] or 0)
    for _restriction, bucket in by_restriction.items():
        bucket["change_net_assets_cents"] = (
            bucket["revenue_cents"] - bucket["expense_cents"]
        )

    by_fund = {
        (r["fund_id"] or "-"): {
            "name": r["fund_name"],
            "restriction_type": r["restriction_type"],
            "revenue_cents": int(r["revenue_cents"] or 0),
            "expense_cents": int(r["expense_cents"] or 0),
        }
        for r in fund_rows
    }
    by_project = {
        (r["project_id"] or "-"): {
            "name": r["project_name"],
            "revenue_cents": int(r["revenue_cents"] or 0),
            "expense_cents": int(r["expense_cents"] or 0),
        }
        for r in proj_rows
    }
    revenue_total = sum(int(r["revenue_cents"] or 0) for r in fund_rows)
    expense_total = sum(int(r["expense_cents"] or 0) for r in fund_rows)

    return {
        "period": {
            "key": period.key,
            "label": period.label,
            "starts_on": period.starts_on,
            "ends_on": period.ends_on,
        },
        "summary": {
            "revenue_cents": revenue_total,
            "expense_cents": expense_total,
            "change_net_assets_cents": revenue_total - expense_total,
        },
        "by_restriction": by_restriction,
        "by_fund": by_fund,
        "by_project": by_project,
    }
