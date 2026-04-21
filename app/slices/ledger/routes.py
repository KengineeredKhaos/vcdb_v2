# app/slices/ledger/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.lib.security import rbac

from .services import verify_chain

bp = Blueprint(
    "ledger", __name__, url_prefix="/ledger", template_folder="templates"
)


# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=ledger_route_access
@bp.get("/verify")
@login_required
@rbac("admin")
def verify_endpoint():
    chain_key = request.args.get("chain_key") or None
    return jsonify(verify_chain(chain_key))
