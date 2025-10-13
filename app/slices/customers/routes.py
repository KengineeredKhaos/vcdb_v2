# app/slices/customers/routes.py
from __future__ import annotations

from re import template

from flask import jsonify, request

from app.lib.request_ctx import ensure_request_id, get_actor_ulid

from . import bp
from . import services as cust_svc


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


@bp.post("")
def ensure_customer():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        entity_ulid = (payload.get("entity_ulid") or "").strip()
        if not entity_ulid:
            return _err("entity_ulid is required", 400)
        customer_ulid = cust_svc.ensure_customer(
            entity_ulid=entity_ulid, request_id=req, actor_id=actor
        )
        return _ok({"customer_ulid": customer_ulid})
    except Exception as e:
        return _err(e)


@bp.get("/<customer_ulid>")
def view_customer(customer_ulid: str):
    dto = cust_svc.customer_view(customer_ulid)
    if not dto:
        return _err("not found", 404)
    return _ok(dto)


@bp.post("/<customer_ulid>/needs/tier1")
def update_tier1(customer_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        hist_ulid = cust_svc.update_tier1(
            customer_ulid=customer_ulid,
            payload=payload,
            request_id=req,
            actor_id=actor,
        )
        dto = cust_svc.customer_view(customer_ulid)
        return _ok({"history_ulid": hist_ulid, "customer": dto})
    except Exception as e:
        return _err(e)


@bp.post("/<customer_ulid>/needs/tier2")
def update_tier2(customer_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        hist_ulid = cust_svc.update_tier2(
            customer_ulid=customer_ulid,
            payload=payload,
            request_id=req,
            actor_id=actor,
        )
        dto = cust_svc.customer_view(customer_ulid)
        return _ok({"history_ulid": hist_ulid, "customer": dto})
    except Exception as e:
        return _err(e)


@bp.post("/<customer_ulid>/needs/tier3")
def update_tier3(customer_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        hist_ulid = cust_svc.update_tier3(
            customer_ulid=customer_ulid,
            payload=payload,
            request_id=req,
            actor_id=actor,
        )
        dto = cust_svc.customer_view(customer_ulid)
        return _ok({"history_ulid": hist_ulid, "customer": dto})
    except Exception as e:
        return _err(e)
