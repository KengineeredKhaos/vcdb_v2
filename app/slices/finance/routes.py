# app/slices/finance/routes.py
from __future__ import annotations

from datetime import UTC

from flask import (
    abort,
    Blueprint,
    render_template,
    request,
)
from flask_login import login_required

from app.lib.chrono import utc_year_month
from app.extensions import db
from app.slices.finance.models import Grant
from app.slices.finance.services_report import statement_of_activities as _soa
from app.slices.finance import services_grants as _grants

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
        period = utc_year_month()

    report = _soa(period)
    return render_template(
        "finance/activities.html",
        report=report,
        period=report["period"]["key"],
    )


@bp.get("/grants/<grant_ulid>/accountability")
# @login_required
def grant_accountability_report(grant_ulid: str):
    grant = db.session.get(Grant, grant_ulid)
    if grant is None:
        abort(404)

    period_start = request.args.get("start_on") or grant.start_on
    period_end = request.args.get("end_on") or grant.end_on

    report = _grants.prepare_grant_report(
        {
            "grant_ulid": grant_ulid,
            "period_start": period_start,
            "period_end": period_end,
        }
    )
    return render_template(
        "finance/grant_accountability.html",
        report=report,
    )
