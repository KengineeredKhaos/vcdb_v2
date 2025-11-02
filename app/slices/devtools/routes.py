# app/slices/devtools/routes.py
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request, session

from app.lib.security import ASSUME_KEY, current_domain_roles
from app.slices.auth.decorators import rbac

# your existing RBAC decorator

bp = Blueprint("devtools", __name__, url_prefix="/dev")
ALLOWED_DOMAIN_ROLES = {
    "customer",
    "staff",
    "sponsor",
    "resource",
    "governor",
}
# extend as needed


def _guard_nonprod():
    return current_app.config.get("APP_MODE") != "production"


@bp.route("/assume", methods=["POST"])
@rbac("dev")
def dev_assume():
    if not _guard_nonprod():
        return jsonify(ok=False, error="disabled in production"), 403
    roles = request.json.get("roles", [])
    bad = [r for r in roles if r not in ALLOWED_DOMAIN_ROLES]
    if bad:
        return jsonify(ok=False, error=f"invalid roles: {bad}"), 400
    session[ASSUME_KEY] = roles
    return jsonify(ok=True, assumed=roles)


@bp.route("/clear", methods=["POST"])
@rbac("dev")
def dev_clear():
    if not _guard_nonprod():
        return jsonify(ok=False, error="disabled in production"), 403
    session.pop(ASSUME_KEY, None)
    return jsonify(ok=True, assumed=[])


@bp.route("/whoami", methods=["GET"])
@rbac("dev")
def dev_whoami():
    if not _guard_nonprod():
        return jsonify(ok=False, error="disabled in production"), 403
    user = getattr(g, "current_user", None)
    return jsonify(
        ok=True,
        app_mode=current_app.config.get("APP_MODE"),
        db_roles=getattr(user, "domain_roles", []),
        assumed=session.get(ASSUME_KEY, []),
        effective=current_domain_roles(user),
    )
