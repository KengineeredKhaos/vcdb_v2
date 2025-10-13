# app/web.py
from flask import Blueprint, current_app, jsonify, render_template

# export as `bp` to match app factory import
bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    return render_template("layout/index.html")


@bp.get("/healthz")
def healthz():
    return jsonify(
        status="ok",
        app="vcdb-v2",
        env=current_app.config.get("ENV", "unknown"),
    )
