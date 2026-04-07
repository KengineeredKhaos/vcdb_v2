# app/slices/finance/services_report.py

from __future__ import annotations

from calendar import monthrange

from sqlalchemy import text

from app.extensions import db
"""
# NOTE: This is intentionally written using SQL text for portability.
# Project truth belongs to Calendar; Finance report rollups therefore group on
# finance_journal_line.project_ulid directly and do not depend on a local
# finance_project shadow table.
# Revenue accounts assumed to start with '4', expense with '5'/'6'.
"""
def _period_meta(period: object) -> dict[str, object]:
    if hasattr(period, "key"):
        return {
            "key": getattr(period, "key", None),
            "label": getattr(period, "label", None),
            "starts_on": getattr(period, "starts_on", None),
            "ends_on": getattr(period, "ends_on", None),
        }

    key = str(period)
    starts_on = None
    ends_on = None
    try:
        year_s, month_s = key.split("-", 1)
        year = int(year_s)
        month = int(month_s)
        last_day = monthrange(year, month)[1]
        starts_on = f"{year:04d}-{month:02d}-01"
        ends_on = f"{year:04d}-{month:02d}-{last_day:02d}"
    except Exception:  # noqa: BLE001
        pass
    return {
        "key": key,
        "label": key,
        "starts_on": starts_on,
        "ends_on": ends_on,
    }


def statement_of_activities(period: str) -> dict[str, object]:
    meta = _period_meta(period)

    q_fund = text(
        """
        SELECT
            COALESCE(f.ulid, '-') AS fund_id,
            COALESCE(f.code, jl.fund_code) AS fund_code,
            COALESCE(f.name, jl.fund_code) AS fund_name,
            COALESCE(f.restriction, 'unrestricted') AS restriction_type,
            -SUM(CASE
                  WHEN jl.account_code LIKE '4%'
                  THEN jl.amount_cents
                  ELSE 0
                END) AS revenue_cents,
            SUM(CASE
                  WHEN jl.account_code LIKE '5%'
                    OR jl.account_code LIKE '6%'
                  THEN jl.amount_cents
                  ELSE 0
                END) AS expense_cents
        FROM finance_journal j
        JOIN finance_journal_line jl ON jl.journal_ulid = j.ulid
        LEFT JOIN finance_fund f ON f.code = jl.fund_code
        WHERE j.period_key = :period
        GROUP BY COALESCE(f.ulid, '-'),
                 COALESCE(f.code, jl.fund_code),
                 COALESCE(f.name, jl.fund_code),
                 COALESCE(f.restriction, 'unrestricted')
        ORDER BY fund_name
        """
    )
    fund_rows = (
        db.session.execute(q_fund, {"period": meta["key"]})
        .mappings()
        .all()
    )

    # Aggregate by project using the journal line project ULID directly.
    # Calendar owns project identity; Finance must not collapse multiple
    # real project ULIDs into one '(unassigned)' bucket merely because a
    # local shadow row is absent.
    q_proj = text(
        """
        SELECT
            COALESCE(jl.project_ulid, '-') AS project_id,
            COALESCE(jl.project_ulid, '(unassigned)') AS project_name,
            -SUM(CASE
                  WHEN jl.account_code LIKE '4%'
                  THEN jl.amount_cents
                  ELSE 0
                END) AS revenue_cents,
            SUM(CASE
                  WHEN jl.account_code LIKE '5%'
                    OR jl.account_code LIKE '6%'
                  THEN jl.amount_cents
                  ELSE 0
                END) AS expense_cents
        FROM finance_journal j
        JOIN finance_journal_line jl ON jl.journal_ulid = j.ulid
        WHERE j.period_key = :period
        GROUP BY COALESCE(jl.project_ulid, '-')
        ORDER BY project_name
        """
    )
    project_rows = (
        db.session.execute(q_proj, {"period": meta["key"]})
        .mappings()
        .all()
    )

    by_restriction: dict[str, dict[str, int]] = {}
    for row in fund_rows:
        key = str(row["restriction_type"])
        bucket = by_restriction.setdefault(
            key,
            {
                "revenue_cents": 0,
                "expense_cents": 0,
                "change_net_assets_cents": 0,
            },
        )
        bucket["revenue_cents"] += int(row["revenue_cents"] or 0)
        bucket["expense_cents"] += int(row["expense_cents"] or 0)

    for bucket in by_restriction.values():
        bucket["change_net_assets_cents"] = (
            bucket["revenue_cents"] - bucket["expense_cents"]
        )

    by_fund = {
        str(row["fund_id"]): {
            "code": row["fund_code"],
            "name": row["fund_name"],
            "restriction_type": row["restriction_type"],
            "revenue_cents": int(row["revenue_cents"] or 0),
            "expense_cents": int(row["expense_cents"] or 0),
        }
        for row in fund_rows
    }
    by_project = {
        str(row["project_id"]): {
            "name": row["project_name"],
            "revenue_cents": int(row["revenue_cents"] or 0),
            "expense_cents": int(row["expense_cents"] or 0),
        }
        for row in project_rows
    }

    revenue_total = sum(int(r["revenue_cents"] or 0) for r in fund_rows)
    expense_total = sum(int(r["expense_cents"] or 0) for r in fund_rows)

    return {
        "period": meta,
        "summary": {
            "revenue_cents": revenue_total,
            "expense_cents": expense_total,
            "change_net_assets_cents": revenue_total - expense_total,
        },
        "by_restriction": by_restriction,
        "by_fund": by_fund,
        "by_project": by_project,
    }
