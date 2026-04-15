# app/web.py
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    return render_template("layout/index.html")
