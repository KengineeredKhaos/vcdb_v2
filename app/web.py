# app/web.py
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("web", __name__)


# VCDB-SEC: PUBLIC entry=public authority=none reason=public_surface test=web_entry_smoke
@bp.get("/")
def index():
    return render_template("layout/index.html")
