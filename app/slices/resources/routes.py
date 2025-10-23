# app/slices/resources/routes.py
from __future__ import annotations

from flask import jsonify, request

from app.lib.request_ctx import ensure_request_id, get_actor_ulid

from . import bp
from . import services as res_svc


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


@bp.post("")
def ensure_resource():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        entity_ulid = (payload.get("entity_ulid") or "").strip()
        if not entity_ulid:
            return _err("entity_ulid is required", 400)
        req = ensure_request_id()
        actor = get_actor_ulid()
        resource_ulid = res_svc.ensure_resource(
            entity_ulid=entity_ulid, request_id=req, actor_ulid=actor
        )
        return _ok({"resource_ulid": resource_ulid})
    except Exception as e:
        return _err(e)


@bp.get("/<resource_ulid>")
def get_resource(resource_ulid: str):
    dto = res_svc.resource_view(resource_ulid)
    if not dto:
        return _err("not found", 404)
    return _ok(dto)


@bp.post("/<resource_ulid>/capabilities")
def upsert_capabilities(resource_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        hist_ulid = res_svc.upsert_capabilities(
            resource_ulid=resource_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
            idempotency_key=req,
        )
        dto = res_svc.resource_view(resource_ulid)
        return _ok({"history_ulid": hist_ulid or None, "resource": dto})
    except Exception as e:
        return _err(e)


@bp.get("")
def search_resources():
    try:
        # Example: /resources?any=basic_needs.food_pantry,events.food_service&review=true
        any_param = request.args.get("any", "").strip()
        all_param = request.args.get("all", "").strip()
        review = request.args.get("review")
        ready = request.args.get("readiness")

        def _parse_pairs(s: str):
            out = []
            if not s:
                return out
            for token in s.split(","):
                token = token.strip()
                if not token:
                    continue
                if "." not in token:
                    continue
                d, k = token.split(".", 1)
                out.append((d.strip(), k.strip()))
            return out

        any_of = _parse_pairs(any_param)
        all_of = _parse_pairs(all_param)

        admin_review_required = (
            None
            if review is None
            else (review.lower() in ("1", "true", "yes"))
        )
        readiness_in = [
            p.strip() for p in (ready or "").split(",") if p.strip()
        ] or None

        page = request.args.get("page", type=int, default=1)
        per = request.args.get("per", type=int, default=50)

        rows, total = res_svc.find_resources(
            any_of=any_of or None,
            all_of=all_of or None,
            admin_review_required=admin_review_required,
            readiness_in=readiness_in,
            page=page,
            per=per,
        )
        return _ok({"rows": rows, "total": total, "page": page, "per": per})
    except Exception as e:
        return _err(e)


@bp.post("/<resource_ulid>/readiness")
def set_readiness(resource_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()
        req = ensure_request_id()
        actor = get_actor_ulid()
        from .services import set_readiness_status

        set_readiness_status(
            resource_ulid=resource_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        return _ok({"readiness_status": status})
    except Exception as e:
        return _err(e)


@bp.post("/<resource_ulid>/mou")
def set_mou(resource_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()
        req = ensure_request_id()
        actor = get_actor_ulid()
        from .services import set_mou_status

        set_mou_status(
            resource_ulid=resource_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        return _ok({"mou_status": status})
    except Exception as e:
        return _err(e)


@bp.post("/<resource_ulid>/capabilities/rebuild")
def rebuild_index(resource_ulid: str):
    try:
        req = ensure_request_id()
        actor = get_actor_ulid()
        from .services import rebuild_capability_index

        rows = rebuild_capability_index(
            resource_ulid=resource_ulid, request_id=req, actor_ulid=actor
        )
        dto = res_svc.resource_view(resource_ulid)
        return _ok({"reindexed_rows": rows, "resource": dto})
    except Exception as e:
        return _err(e)


@bp.post("/<resource_ulid>/readiness/promote_if_clean")
def promote_if_clean(resource_ulid: str):
    try:
        req = ensure_request_id()
        actor = get_actor_ulid()
        from .services import promote_readiness_if_clean

        promoted = promote_readiness_if_clean(
            resource_ulid=resource_ulid, request_id=req, actor_ulid=actor
        )
        dto = res_svc.resource_view(resource_ulid)
        return _ok({"promoted": promoted, "resource": dto})
    except Exception as e:
        return _err(e)


@bp.patch("/<resource_ulid>/capabilities")
def patch_capabilities(resource_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        from .services import patch_capabilities as svc_patch

        hist_ulid = svc_patch(
            resource_ulid=resource_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        dto = res_svc.resource_view(resource_ulid)
        return _ok({"history_ulid": hist_ulid, "resource": dto})
    except Exception as e:
        return _err(e)


@bp.post("/capabilities/rebuild_all")
def rebuild_all():
    try:
        req = ensure_request_id()
        actor = get_actor_ulid()
        page = request.args.get("page", type=int, default=1)
        per = request.args.get("per", type=int, default=200)
        from .services import rebuild_all_capability_indexes

        summary = rebuild_all_capability_indexes(
            page=page, per=per, request_id=req, actor_ulid=actor
        )
        return _ok(summary)
    except Exception as e:
        return _err(e)
