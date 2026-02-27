# app/slices/finance/routes.py
from __future__ import annotations

from datetime import UTC

from flask import (
    Blueprint,
    render_template,
    request,
)
from flask_login import login_required

from app.slices.finance.services_report import statement_of_activities as _soa

bp = Blueprint(
    "finance",
    __name__,
    template_folder="templates",
    url_prefix="/finance",
)


@bp.get("/hello")
@login_required
def hello():
    return render_template("finance/hello.html", title="Finance • Hello")


@bp.get(
    "/journal", endpoint="journal_index"
)  # name used in Option A fallback
def journal_index():
    # Replace with a real listing later
    return render_template(
        "layout/placeholder.html",
        title="Journal",
        message="Journal UI coming soon",
    )


@bp.get("/activities")
def activities_report():
    period = request.args.get("period")
    if not period:
        # naive default: current YYYY-MM from UTC now
        from datetime import datetime

        period = datetime.now(UTC).strftime("%Y-%m")

    report = _soa(period)
    return render_template(
        "finance/activities.html", report=report, period=period
    )
