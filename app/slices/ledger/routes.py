# app/slices/ledger/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.extensions import auth_ctx, db
from app.lib.request_ctx import ensure_request_id
from app.lib.security import rbac

from .services import latest_daily_close_status, run_daily_close, verify_chain

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


# VCDB-SEC: ACTIVE entry=admin authority=rbac reason=admin_only_surface
@bp.post("/daily-close", endpoint="daily_close")
@login_required
@rbac("admin")
def daily_close_post():
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()
    chain_key = request.form.get("chain_key") or None

    try:
        result = run_daily_close(
            request_id=req,
            actor_ulid=actor,
            chain_key=chain_key,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return jsonify(result), 200 if result.get("ok") else 409


# VCDB-SEC: ACTIVE entry=admin authority=rbac reason=admin_only_surface
@bp.get("/daily-close/status", endpoint="daily_close_status")
@login_required
@rbac("admin")
def daily_close_status_get():
    return jsonify(latest_daily_close_status())


# Register Ledger admin-issue routes on this slice blueprint.
# Keep this import at the bottom so admin_issue_routes can import `bp`
# from this module without creating a circular import.
from . import admin_issue_routes as _admin_issue_routes  # noqa: E402,F401
