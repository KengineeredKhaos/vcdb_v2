# app/slices/finance/routes.py
from __future__ import annotations

import hashlib
import json as _json

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
