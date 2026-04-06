# app/slices/finance/routes_report.py
from __future__ import annotations

from datetime import UTC

from flask import Blueprint, render_template, request

from app.lib.chrono import utc_year_month
from app.slices.finance.services_report import statement_of_activities as _soa

bp = Blueprint("finance_reports", __name__, url_prefix="/finance/reports")


@bp.get("/activities")
def activities_report():
    period = request.args.get("period")
    if not period:
        period = utc_year_month()

    report = _soa(period)
    return render_template(
        "finance/activities.html", report=report, period=period
    )
