# app/slices/governance/routes.py
from __future__ import annotations
from flask import Blueprint, request, jsonify

from app.lib.request_ctx import get_actor_ulid
from . import services as svc
from app.extensions.contracts import governance_v2

bp = Blueprint("governance", __name__, url_prefix="/governance")

def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


@bp.get("/policies")
def list_keys():
    return _ok({"keys": svc.list_policy_keys()})


@bp.get("/policies/<path:family>")
def get_value(family: str):
    try:
        return _ok(svc.get_policy_value(family))
    except Exception as e:
        return _err(e, 404)


@bp.post("/policies/<path:family>")
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


@bp.get("/canonicals")
def canonicals():
    return jsonify(
        {
            "states": svc.list_states(),
            "service_classifications": svc.list_service_classifications(),
            "role_codes": svc.list_role_codes(),
        }
    )


@bp.get("/roles")
def roles():
    d = governance_v2.describe()
    return jsonify({"domain_roles": d["domain_roles"], "rbac_to_domain": d["rbac_to_domain"]})
