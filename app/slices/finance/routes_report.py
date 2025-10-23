# app/slices/finance/routes_report.py
from __future__ import annotations

from flask import Blueprint, render_template, request

from app.slices.finance.services_report import statement_of_activities as _soa

bp = Blueprint("finance_reports", __name__, url_prefix="/finance/reports")


@bp.get("/activities")
def activities_report():
    period = request.args.get("period")
    if not period:
        # naive default: current YYYY-MM from UTC now
        from datetime import datetime, timezone

        period = datetime.now(timezone.utc).strftime("%Y-%m")

    report = _soa(period)
    return render_template(
        "finance/activities.html", report=report, period=period
    )
