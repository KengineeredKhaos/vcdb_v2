# app/slices/ledger/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.lib.security import rbac

from .services import verify_chain

bp = Blueprint(
    "ledger", __name__, url_prefix="/ledger", template_folder="templates"
)

# Register Ledger admin-issue routes on this slice blueprint.
# Keep this at the bottom so admin_issue_routes can import `bp`
# from this module without creating a circular import.
from . import admin_issue_routes as _admin_issue_routes  # noqa: E402,F401


# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=ledger_route_access
@bp.get("/verify")
@login_required
@rbac("admin")
def verify_endpoint():
    chain_key = request.args.get("chain_key") or None
    return jsonify(verify_chain(chain_key))
