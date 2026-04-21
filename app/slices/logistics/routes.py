# app/slices/logistics/routes.py
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import select

from app.extensions import db
from app.lib.request_ctx import ensure_request_id, get_actor_ulid
from app.lib.security import rbac

from . import services as svc
from .issuance_services import issue_inventory as issue_inventory_service
from .models import Location

bp = Blueprint(
    "logistics",
    __name__,
    url_prefix="/logistics",
    template_folder="templates",
)


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


def _location_rows() -> list[Location]:
    return list(
        db.session.execute(
            select(Location).order_by(Location.code.asc())
        ).scalars()
    )


def _cart_lines_from_form(line_count: int) -> list[dict[str, int | str]]:
    lines: list[dict[str, int | str]] = []
    for idx in range(1, line_count + 1):
        sku_code = str(request.form.get(f"sku_{idx}") or "").strip()
        qty_raw = str(request.form.get(f"qty_{idx}") or "0").strip()
        try:
            qty_each = int(qty_raw or 0)
        except ValueError:
            qty_each = 0
        if sku_code and qty_each > 0:
            lines.append({"sku_code": sku_code, "qty_each": qty_each})
    return lines


def _commit_or_rollback(data: dict | None = None):
    db.session.commit()
    return _ok(data)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.post("/locations")
@login_required
@rbac("staff", "admin")
def ensure_location():
    try:
        p = request.get_json(force=True)
        ulid = svc.ensure_location(code=p["code"], name=p["name"])
        return _commit_or_rollback({"location_ulid": ulid})
    except Exception as e:
        db.session.rollback()
        return _err(e)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.post("/items")
@login_required
@rbac("staff", "admin")
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
        return _commit_or_rollback({"item_ulid": ulid})
    except Exception as e:
        db.session.rollback()
        return _err(e)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.get("/items/by-sku/<sku>")
@login_required
@rbac("staff", "admin")
def item_by_sku(sku: str):
    dto = svc.find_item_by_sku(sku)
    return _ok(dto) if dto else _err("not found", 404)


# VCDB-SEC: OPEN entry=authenticated_user authority=login_required reason=needs_matrix_decision
# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.post("/receive")
@login_required
@rbac("staff", "admin")
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
        return _commit_or_rollback(out)
    except Exception as e:
        db.session.rollback()
        return _err(e)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.post("/issue")
@login_required
@rbac("staff", "admin")
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

        if out.get("ok"):
            db.session.commit()
            return jsonify(out), 200

        db.session.rollback()
        return jsonify(out), 400

    except Exception as e:
        db.session.rollback()
        return _err(e)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.post("/transfer")
@login_required
@rbac("staff", "admin")
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
        return _commit_or_rollback(out)
    except Exception as e:
        db.session.rollback()
        return _err(e)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.post("/stock/rebuild")
@login_required
@rbac("staff", "admin")
def stock_rebuild():
    try:
        p = request.get_json(force=True) or {}
        out = svc.rebuild_stock(
            item_ulid=p.get("item_ulid"), location_ulid=p.get("location_ulid")
        )
        return _commit_or_rollback(out)
    except Exception as e:
        db.session.rollback()
        return _err(e)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.get("/items/<item_ulid>")
@login_required
@rbac("staff", "admin")
def get_item(item_ulid: str):
    dto = svc.item_view(item_ulid)
    return _ok(dto) if dto else _err("not found", 404)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.get("/customers/<customer_ulid>/issue-cart")
@login_required
@rbac("staff", "admin")
def customer_issue_cart_get(customer_ulid: str):
    ensure_request_id()
    preview = None
    location_ulid = str(request.args.get("location_ulid") or "").strip()
    if location_ulid:
        from app.extensions.contracts import logistics_v2

        preview = logistics_v2.preview_customer_issuance_cart(
            customer_ulid=customer_ulid,
            location_ulid=location_ulid,
        )

    return render_template(
        "logistics/customer_issue_cart.html",
        customer_ulid=customer_ulid,
        locations=_location_rows(),
        selected_location_ulid=location_ulid or None,
        preview=preview,
    )


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=logistics_route_access
@bp.post("/customers/<customer_ulid>/issue-cart")
@login_required
@rbac("staff", "admin")
def customer_issue_cart_post(customer_ulid: str):
    actor_ulid = get_actor_ulid()
    if not actor_ulid and current_app.config.get("AUTH_MODE") == "stub":
        actor_ulid = (
            str(current_app.config.get("DEV_ACTOR_ULID") or "").strip()
            or None
        )
    if not actor_ulid:
        abort(403)

    location_ulid = str(request.form.get("location_ulid") or "").strip()
    try:
        line_count = int(request.form.get("line_count") or 0)
    except ValueError:
        line_count = 0

    cart_lines = _cart_lines_from_form(line_count)
    override_cadence = bool(request.form.get("override_cadence"))
    override_reason = (
        str(request.form.get("override_reason") or "").strip() or None
    )
    session_note = str(request.form.get("session_note") or "").strip() or None

    try:
        from app.extensions.contracts import logistics_v2

        result = logistics_v2.commit_customer_issuance_cart(
            customer_ulid=customer_ulid,
            location_ulid=location_ulid,
            cart_lines=cart_lines,
            actor_ulid=actor_ulid,
            request_id=ensure_request_id(),
            session_note=session_note,
            override_cadence=override_cadence,
            override_reason=override_reason,
        )
        db.session.commit()
        flash("Supplies issued and customer history updated.", "success")
        return redirect(
            url_for(
                "customers.customer_history_detail_get",
                entity_ulid=customer_ulid,
                history_ulid=result["history_ulid"],
            )
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("customer_issue_cart_post failed")
        if current_app.debug:
            raise
        flash(str(exc), "error")
        return redirect(
            url_for(
                "logistics.customer_issue_cart_get",
                customer_ulid=customer_ulid,
                location_ulid=location_ulid,
            )
        )
