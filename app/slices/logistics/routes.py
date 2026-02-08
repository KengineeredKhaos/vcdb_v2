# app/slices/logistics/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.lib.request_ctx import get_actor_ulid

from . import services as svc
from .issuance_services import issue_inventory as issue_inventory_service

bp = Blueprint("logistics", __name__, url_prefix="/logistics")


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


@bp.post("/locations")
def ensure_location():
    try:
        p = request.get_json(force=True)
        ulid = svc.ensure_location(code=p["code"], name=p["name"])
        return _ok({"location_ulid": ulid})
    except Exception as e:
        return _err(e)


@bp.post("/items")
def ensure_item():
    try:
        p = request.get_json(force=True)
        ulid = svc.ensure_item(
            category=p["category"],
            name=p["name"],
            unit=p["unit"],
            condition=p.get("condition", "mixed"),
            sku=p.get("sku"),
            sku_parts=p.get("sku_parts"),
            sku_bin_location=p.get("bin"),
            sku_nsx=p.get("nsx"),
        )
        return _ok({"item_ulid": ulid})
    except Exception as e:
        return _err(e)


@bp.get("/items/by-sku/<sku>")
def item_by_sku(sku: str):
    dto = svc.find_item_by_sku(sku)
    return _ok(dto) if dto else _err("not found", 404)


@bp.post("/receive")
def receive():
    try:
        p = request.get_json(force=True)
        out = svc.receive_inventory(
            item_ulid=p["item_ulid"],
            quantity=p["quantity"],
            unit=p["unit"],
            source=p["source"],
            received_at_utc=p["received_at_utc"],
            location_ulid=p["location_ulid"],
            source_entity_ulid=p.get("source_entity_ulid"),
            note=p.get("note"),
            actor_ulid=get_actor_ulid(),
        )
        return _ok(out)
    except Exception as e:
        return _err(e)


@bp.post("/issue")
def issue():
    """Issue an item to a customer (policy + stock enforced)."""
    try:
        p = request.get_json(force=True) or {}

        sku_code = p.get("sku_code") or p.get("sku")
        if not sku_code:
            return _err("missing field: sku_code")

        qty_each = int(p.get("quantity") or p.get("qty_each") or 1)

        out = issue_inventory_service(
            customer_ulid=p.get("customer_ulid"),
            sku_code=sku_code,
            qty_each=qty_each,
            when_iso=p.get("when_iso"),
            project_ulid=p.get("project_ulid"),
            location_ulid=p.get("location_ulid"),
            batch_ulid=p.get("batch_ulid"),
            actor_ulid=get_actor_ulid(),
            actor_domain_roles=p.get("actor_domain_roles") or [],
            override_cadence=bool(p.get("override_cadence")),
            request_id=p.get("request_id"),
            reason=p.get("reason"),
            note=p.get("note"),
        )

        status = 200 if out.get("ok") else 400
        return jsonify(out), status

    except Exception as e:
        return _err(e)


@bp.post("/transfer")
def transfer():
    try:
        p = request.get_json(force=True)
        out = svc.transfer_inventory(
            item_ulid=p["item_ulid"],
            quantity=p["quantity"],
            unit=p["unit"],
            happened_at_utc=p["happened_at_utc"],
            location_from_ulid=p["location_from_ulid"],
            location_to_ulid=p["location_to_ulid"],
            note=p.get("note"),
            actor_ulid=get_actor_ulid(),
            batch_ulid=p.get("batch_ulid"),
        )
        return _ok(out)
    except Exception as e:
        return _err(e)


@bp.get("/stock")
def stock():
    try:
        item = request.args.get("item_ulid")
        loc = request.args.get("location_ulid")
        return _ok(
            {"rows": svc.stock_view(item_ulid=item, location_ulid=loc)}
        )
    except Exception as e:
        return _err(e)


@bp.post("/stock/rebuild")
def stock_rebuild():
    try:
        p = request.get_json(force=True) or {}
        out = svc.rebuild_stock(
            item_ulid=p.get("item_ulid"), location_ulid=p.get("location_ulid")
        )
        return _ok(out)
    except Exception as e:
        return _err(e)


@bp.get("/items/<item_ulid>")
def get_item(item_ulid: str):
    dto = svc.item_view(item_ulid)
    return _ok(dto) if dto else _err("not found", 404)
