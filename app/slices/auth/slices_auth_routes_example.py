# slices/auth/routes.py (example)
from flask import Blueprint, current_app, jsonify, request

from app.extensions.policies import AUTH_DATA, save_policy
from app.slices.auth.decorators import rbac

bp = Blueprint("auth_policies", __name__)


@bp.route("/admin/policy/rbac", methods=["PUT"])
@rbac("admin")
def put_policy_rbac():
    payload = request.get_json(force=True)

    def _audit(evt):
        current_app.logger.info("policy_audit %s", evt)

    saved = save_policy(
        AUTH_DATA / "policy_rbac.json",
        payload,
        schema_name=None,
        auditor=_audit,
    )
    return jsonify(ok=True, version=saved.get("version"))
