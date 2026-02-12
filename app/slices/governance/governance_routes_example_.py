# slices/governance/routes.py (example)
from flask import Blueprint, current_app, jsonify, request

from app.extensions.policies import GOV_DATA, save_policy
from app.lib.security import rbac, require_domain_roles_any

bp = Blueprint("governance_policies", __name__)


@bp.route("/admin/policy/issuance", methods=["PUT"])
@rbac("admin")
@require_domain_roles_any("governor")
def put_policy_issuance():
    payload = request.get_json(force=True)

    def _audit(evt):
        current_app.logger.info("policy_audit %s", evt)

    saved = save_policy(
        GOV_DATA / "policy_issuance.json",
        payload,
        schema_name="policy_issuance.schema.json",
        auditor=_audit,
    )
    return jsonify(ok=True, version=saved.get("version"))


@bp.route("/admin/policy/domain", methods=["PUT"])
@rbac("admin")
@require_domain_roles_any("governor")
def put_policy_domain():
    payload = request.get_json(force=True)

    def _audit(evt):
        current_app.logger.info("policy_audit %s", evt)

    saved = save_policy(
        GOV_DATA / "policy_domain.json",
        payload,
        schema_name="policy_domain.schema.json",
        auditor=_audit,
    )
    return jsonify(ok=True, version=saved.get("version"))
