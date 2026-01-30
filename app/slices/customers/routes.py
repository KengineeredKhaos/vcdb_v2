# app/slices/customers/routes.py
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from flask import jsonify, request

from app.extensions import db
from app.extensions.errors import ContractError
from app.lib.request_ctx import ensure_request_id, get_actor_ulid
from app.services.entity_validate import require_person_entity_ulid

from . import bp


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _dto_to_dict(dto):
    if dto is None:
        return None
    if isinstance(dto, dict):
        return dto
    if is_dataclass(dto):
        return asdict(dto)
    # last resort (namedtuple-ish)
    return dict(dto)


def _err(exc: Exception | str, code: int = 400):
    if isinstance(exc, ContractError):
        payload = {
            "ok": False,
            "error": exc.message,
            "code": exc.code,
            "where": exc.where,
        }
        if getattr(exc, "data", None):
            payload["data"] = exc.data
        return jsonify(payload), exc.http_status

    if isinstance(exc, NotImplementedError):
        return jsonify({"ok": False, "error": "not implemented"}), 501
    if isinstance(exc, PermissionError):
        return jsonify({"ok": False, "error": str(exc)}), 403
    if isinstance(exc, LookupError):
        return jsonify({"ok": False, "error": str(exc)}), 404
    if isinstance(exc, ValueError):
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": False, "error": str(exc)}), code


# -----------------
# Core Customer API (smoke-test surface)
# -----------------


@bp.post("")
# url_prefix="/customers" => binds to /customers (no trailing slash redirect)
def create_customer():
    from . import services as cust_svc

    payload = request.get_json(force=True, silent=False) or {}
    req = ensure_request_id()
    actor = get_actor_ulid()

    entity_ulid = (payload.get("entity_ulid") or "").strip()
    if not entity_ulid:
        return _err(ValueError("entity_ulid is required"), 400)

    try:
        # Enforce that entity exists and is a person (shared guard; uses entity_v2.get_entity_core)
        require_person_entity_ulid(
            db.session, entity_ulid, where="customers.routes.create_customer"
        )

        customer_ulid = cust_svc.ensure_customer(
            entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        data = {
            "ulid": customer_ulid,  # canonical id key
            "customer_ulid": customer_ulid,  # alias (optional, but helps old callers/tests)
            "entity_ulid": entity_ulid,
        }
        db.session.commit()
        return _ok(data, request_id=req)

    except Exception as e:
        db.session.rollback()
        return _err(e)


@bp.get("/<customer_ulid>")
def view_customer(customer_ulid: str):
    from . import services as cust_svc

    dto = cust_svc.get_dashboard_view(
        customer_ulid
    )  # or whatever you named it
    if not dto:
        return _err(LookupError("not found"), 404)

    data = _dto_to_dict(dto)

    # canonical external key
    data["customer_ulid"] = data.get("customer_ulid") or customer_ulid
    data["ulid"] = data.get("ulid") or data["customer_ulid"]

    return _ok(data)


@bp.post("/<customer_ulid>/needs/tier1")
def update_needs_tier1(customer_ulid: str):
    from . import services as cust_svc

    payload = request.get_json(force=True, silent=False) or {}
    req = ensure_request_id()
    actor = get_actor_ulid()
    try:
        hist_ulid = cust_svc.record_needs_tier(
            customer_ulid=customer_ulid,
            tier_key="tier1",
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"history_ulid": hist_ulid}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.post("/<customer_ulid>/needs/tier2")
def update_needs_tier2(customer_ulid: str):
    from . import services as cust_svc

    payload = request.get_json(force=True, silent=False) or {}
    req = ensure_request_id()
    actor = get_actor_ulid()
    try:
        hist_ulid = cust_svc.record_needs_tier(
            customer_ulid=customer_ulid,
            tier_key="tier2",
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"history_ulid": hist_ulid}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e)


@bp.post("/<customer_ulid>/needs/tier3")
def update_needs_tier3(customer_ulid: str):
    from . import services as cust_svc

    payload = request.get_json(force=True, silent=False) or {}
    req = ensure_request_id()
    actor = get_actor_ulid()
    try:
        hist_ulid = cust_svc.record_needs_tier(
            customer_ulid=customer_ulid,
            tier_key="tier3",
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"history_ulid": hist_ulid}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e)


@bp.get("/<customer_ulid>/eligibility")
def get_eligibility(customer_ulid: str):
    dto = cust_svc.get_eligibility_snapshot(customer_ulid)
    if not dto:
        return _err(LookupError("not found"), 404)
    d = asdict(dto)

    d["customer_ulid"] = d.get("customer_ulid") or customer_ulid
    d["ulid"] = d.get("ulid") or d["customer_ulid"]

    return _ok(d)
