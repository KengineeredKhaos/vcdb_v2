# app/slices/governance/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.extensions.contracts import governance_v2
from app.lib.request_ctx import get_actor_ulid
from app.lib.security import rbac

from . import services as svc

bp = Blueprint("governance", __name__, url_prefix="/governance")


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=governance_route_access
@bp.get("/policies")
@login_required
@rbac("admin")
def list_keys():
    return _ok({"keys": svc.list_policy_keys()})


# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=governance_route_access
@bp.get("/policies/<path:family>")
@login_required
@rbac("admin")
def get_value(family: str):
    try:
        return _ok(svc.get_policy_value(family))
    except Exception as e:
        return _err(e, 404)


# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=governance_route_access
@bp.post("/policies/<path:family>")
@login_required
@rbac("admin")
def set_value(family: str):
    try:
        namespace, key = family.split(".", 1)
        payload = request.get_json(force=True) or {}
        row = svc.set_policy(
            namespace, key, payload, actor_entity_ulid=get_actor_ulid()
        )
        return _ok({"policy_ulid": row.ulid, "version": row.version})
    except Exception as e:
        return _err(e)


# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=governance_route_access
@bp.get("/canonicals")
@login_required
@rbac("admin")
def canonicals():
    return jsonify(
        {
            "states": svc.list_states(),
            "service_classifications": svc.list_service_classifications(),
            "role_codes": svc.list_role_codes(),
        }
    )


# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=governance_route_access
@bp.get("/roles")
@login_required
@rbac("admin")
def roles():
    d = governance_v2.describe()
    return jsonify(
        {
            "domain_roles": d["domain_roles"],
            "rbac_to_domain": d["rbac_to_domain"],
        }
    )
