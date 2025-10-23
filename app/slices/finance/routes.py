# app/slices/finance/routes.py
from __future__ import annotations

import hashlib
import json as _json

from app.slices.finance.services_report import statement_of_activities as _soa
from flask import (
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask_login import login_required

from app.extensions import db
from app.utils.paging import Pager

from . import bp


@bp.get("/hello")
@login_required
def hello():
    return render_template("finance/hello.html", title="Finance • Hello")


@bp.get("/ledger", endpoint="journal_index")  # name used in Option A fallback
def ledger_index():
    # Replace with a real listing later
    return render_template(
        "layout/placeholder.html",
        title="Ledger",
        message="Ledger UI coming soon",
    )


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
