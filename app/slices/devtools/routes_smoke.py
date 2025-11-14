# app/slices/devtools/routes_smoke.py
from flask import Blueprint

bp = Blueprint("dev_smoke", __name__)

@bp.get("/")
def index():
    return "VCDB v2 — dev server alive", 200
