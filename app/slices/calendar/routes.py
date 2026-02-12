# Generated scaffolding — VCDB v2 — 2025-09-22 00:11:24 UTC
from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint(
    "calendar",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/calendar",
)


@bp.get("/hello")
@login_required
def hello():
    return render_template("calendar/hello.html", title="Calendar • Hello")
