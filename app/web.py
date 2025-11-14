# app/web.py
from flask import Blueprint, render_template, current_app

bp = Blueprint("web", __name__)

@bp.get("/")
def index():
    env = (current_app.config.get("ENV") or "").lower()
    if env in {"dev", "development", "test", "testing"}:
        return "VCDB v2 — landing (dev/testing)", 200
    # prod: use the real template
    return render_template("layout/index.html")
