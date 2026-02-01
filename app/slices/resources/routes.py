# app/slices/resources/routes.py
"""
Resources slice HTTP routes.

Goal:
- Keep routes skinny: parse input, call services, commit/rollback, shape response.
- PII boundary: never return Entity PII here; only resource entity ULIDs + capability codes.

Endpoints (minimal, test-facing surface):
- POST   /resources                       -> ensure resource for an entity
- GET    /resources?any=domain.key        -> search resources by capability (ANY-of)
- POST   /resources/<resource_entity_ulid>/capabilities  -> replace capabilities (upsert)
- PATCH  /resources/<resource_entity_ulid>/capabilities  -> patch capabilities (note-only, etc.)
"""

from __future__ import annotations

from flask import jsonify, request

from app.extensions import db
from app.extensions.errors import ContractError
from app.lib.request_ctx import ensure_request_id, get_actor_ulid

from . import bp
from . import services as svc


def _ok(data: dict, request_id: str):
    return jsonify({"ok": True, "request_id": request_id, "data": data}), 200


def _err(exc: Exception, code: int = 400):
    # Prefer ContractError shaping
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

    if isinstance(exc, LookupError):
        return jsonify({"ok": False, "error": str(exc)}), 404
    if isinstance(exc, PermissionError):
        return jsonify({"ok": False, "error": str(exc)}), 403
    if isinstance(exc, ValueError):
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": False, "error": str(exc)}), code


def _parse_cap_code(raw: str) -> tuple[str, str]:
    """
    Parse 'domain.key' into ('domain', 'key').
    """
    s = (raw or "").strip()
    if not s or "." not in s:
        raise ValueError("capability code must be 'domain.key'")
    domain, key = s.split(".", 1)
    domain = domain.strip()
    key = key.strip()
    if not domain or not key:
        raise ValueError("capability code must be 'domain.key'")
    return domain, key


@bp.post("")
# url_prefix="/resources" => binds to /resources (no trailing slash redirect)
def ensure_resource():
    payload = request.get_json(force=True, silent=False) or {}
    req = ensure_request_id()
    actor = get_actor_ulid()

    entity_ulid = (payload.get("entity_ulid") or "").strip()
    if not entity_ulid:
        return _err(ValueError("entity_ulid is required"), 400)

    try:
        rid = svc.ensure_resource(
            entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"resource_entity_ulid": rid}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.get("")
def search_resources():
    """
    Minimal capability search:
      /resources?any=basic_needs.food_pantry
    Returns:
      { ok, data: { rows: [...], total, page, per } }
    """
    req = ensure_request_id()

    any_code = (request.args.get("any") or "").strip()
    all_code = (request.args.get("all") or "").strip()

    page = int((request.args.get("page") or 1) or 1)
    per = int((request.args.get("per") or 50) or 50)

    try:
        any_of = None
        all_of = None

        if any_code:
            d, k = _parse_cap_code(any_code)
            any_of = [(d, k)]
        if all_code:
            d, k = _parse_cap_code(all_code)
            all_of = [(d, k)]

        rows, total = svc.find_resources(
            any_of=any_of,
            all_of=all_of,
            page=page,
            per=per,
        )
        return _ok(
            {"rows": rows, "total": total, "page": page, "per": per},
            request_id=req,
        )
    except Exception as e:
        return _err(e, 400)


@bp.post("/<resource_entity_ulid>/capabilities")
def upsert_capabilities(resource_entity_ulid: str):
    payload = request.get_json(force=True, silent=False) or {}
    req = ensure_request_id()
    actor = get_actor_ulid()

    try:
        hist_ulid = svc.upsert_capabilities(
            resource_entity_ulid=resource_entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
            idempotency_key=None,
        )
        view = svc.resource_view(resource_entity_ulid)
        db.session.commit()
        return _ok(
            {"history_ulid": hist_ulid or None, "resource": view},
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.patch("/<resource_entity_ulid>/capabilities")
def patch_capabilities(resource_entity_ulid: str):
    payload = request.get_json(force=True, silent=False) or {}
    req = ensure_request_id()
    actor = get_actor_ulid()

    try:
        hist_ulid = svc.patch_capabilities(
            resource_entity_ulid=resource_entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        view = svc.resource_view(resource_entity_ulid)
        db.session.commit()
        return _ok(
            {"history_ulid": hist_ulid or None, "resource": view},
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)
