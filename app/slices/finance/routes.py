# app/slices/finance/routes.py
from __future__ import annotations

import re

from flask import (
    abort,
    Blueprint,
    render_template,
    request,
)
from flask_login import login_required

from app.extensions import db
from app.lib.chrono import utc_year_month
from app.slices.finance import services_grants as _grants
from app.slices.finance.models import Grant
from app.slices.finance.services_report import statement_of_activities as _soa

bp = Blueprint(
    "finance",
    __name__,
    template_folder="templates",
    url_prefix="/finance",
)

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalized_period(value: str | None) -> str:
    raw = str(value or "").strip()
    if _PERIOD_RE.match(raw):
        return raw
    return utc_year_month()


def _normalized_date(value: str | None, fallback: str | None) -> str | None:
    raw = str(value or "").strip()
    if raw and _DATE_RE.match(raw):
        return raw
    return fallback


@bp.get("/hello")
@login_required
def hello():
    return render_template("finance/hello.html", title="Finance • Hello")


@bp.get(
    "/journal", endpoint="journal_index"
)  # name used in Option A fallback
# Finance is intentionally not exposing a write-oriented journal UI.
def journal_index():
    return render_template(
        "layout/placeholder.html",
        title="Journal",
        message="Journal UI coming soon",
    )


@bp.get("/activities")
def activities_report():
    period = _normalized_period(request.args.get("period"))
    report = _soa(period)
    return render_template(
        "finance/activities.html",
        title="Statement of Activities",
        report=report,
        period=report["period"]["key"],
    )


@bp.get("/grants/<grant_ulid>/accountability")
def grant_accountability_report(grant_ulid: str):
    # Intentionally left readable in the current test/dev regime.
    # Access hardening can be revisited in a dedicated surface pass.
    grant = db.session.get(Grant, grant_ulid)
    if grant is None:
        abort(404)

    period_start = _normalized_date(
        request.args.get("start_on"),
        grant.start_on,
    )
    period_end = _normalized_date(
        request.args.get("end_on"),
        grant.end_on,
    )

    report = _grants.prepare_grant_report(
        {
            "grant_ulid": grant_ulid,
            "period_start": period_start,
            "period_end": period_end,
        }
    )
    return render_template(
        "finance/grant_accountability.html",
        title="Grant Accountability",
        report=report,
    )
