# app/extensions/contracts/governance/v1.py
from __future__ import annotations

import json  # <-- add

from app.extensions import db  # <-- add
from app.extensions.contracts.types import ContractRequest, ContractResponse
from app.lib.chrono import utc_now
from app.slices.governance import services as gov
from app.slices.governance.models import Policy


def roles_list(req: ContractRequest) -> ContractResponse:
    try:
        data = gov.get_policy_value("governance.roles")
        return {
            "contract": "governance.roles.v2/list",
            "request_id": req["request_id"],
            "ts": utc_now(),
            "ok": True,
            "data": data,
        }
    except Exception as e:
        return {
            "contract": "governance.roles.v2/list",
            "request_id": req["request_id"],
            "ts": utc_now(),
            "ok": False,
            "error": {"message": str(e)},
        }


def policy_set(req: ContractRequest) -> ContractResponse:
    # generic setter: { "family": "governance.roles", "value": {...} }
    d = req.get("data", {})
    family = d["family"]
    namespace, key = family.split(".", 1)
    row = gov.set_policy(
        namespace, key, d["value"], actor_entity_ulid=req.get("actor_ulid")
    )
    return {
        "contract": "governance.policy.v2/set",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"policy_ulid": row.ulid, "version": row.version},
    }


def dump_active(req: ContractRequest) -> ContractResponse:
    """
    Return all active policies for cache warmup.
    Shape is stable and small; values are already JSON strings in DB,
    but we return parsed objects.
    """
    rows = (
        db.session.query(Policy)
        .filter(Policy.is_active.is_(True))
        .order_by(Policy.namespace.asc(), Policy.key.asc())
        .all()
    )
    out = []
    for r in rows:
        try:
            val = json.loads(r.value_json)
        except Exception:
            val = {}
        out.append(
            {
                "policy_ulid": r.ulid,
                "namespace": r.namespace,
                "key": r.key,
                "version": r.version,
                "value": val,
            }
        )
    return {
        "contract": "governance.dump_active.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"rows": out},
    }
