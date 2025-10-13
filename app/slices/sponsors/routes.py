# app/slices/sponsors/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.lib.request_ctx import ensure_request_id, get_actor_ulid

from . import services as sp_svc

bp = Blueprint("sponsors", __name__, url_prefix="/sponsors")


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


@bp.post("")
def ensure_sponsor():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        entity_ulid = (payload.get("entity_ulid") or "").strip()
        if not entity_ulid:
            return _err("entity_ulid is required", 400)
        req, actor = ensure_request_id(), get_actor_ulid()
        sponsor_ulid = sp_svc.ensure_sponsor(
            entity_ulid=entity_ulid, request_id=req, actor_id=actor
        )
        return _ok({"sponsor_ulid": sponsor_ulid})
    except Exception as e:
        return _err(e)


@bp.get("/<sponsor_ulid>")
def get_sponsor(sponsor_ulid: str):
    dto = sp_svc.sponsor_view(sponsor_ulid)
    return _ok(dto) if dto else _err("not found", 404)


@bp.post("/<sponsor_ulid>/capabilities")
def upsert_caps(sponsor_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        hist = sp_svc.upsert_capabilities(
            sponsor_ulid=sponsor_ulid,
            payload=payload,
            request_id=req,
            actor_id=actor,
        )
        return _ok(
            {
                "history_ulid": hist,
                "sponsor": sp_svc.sponsor_view(sponsor_ulid),
            }
        )
    except Exception as e:
        return _err(e)


@bp.patch("/<sponsor_ulid>/capabilities")
def patch_caps(sponsor_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        hist = sp_svc.patch_capabilities(
            sponsor_ulid=sponsor_ulid,
            payload=payload,
            request_id=req,
            actor_id=actor,
        )
        return _ok(
            {
                "history_ulid": hist,
                "sponsor": sp_svc.sponsor_view(sponsor_ulid),
            }
        )
    except Exception as e:
        return _err(e)


@bp.post("/<sponsor_ulid>/readiness")
def set_readiness(sponsor_ulid: str):
    try:
        status = (
            (request.get_json(force=True).get("status") or "").strip().lower()
        )
        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_readiness_status(
            sponsor_ulid=sponsor_ulid,
            status=status,
            request_id=req,
            actor_id=actor,
        )
        return _ok({"readiness_status": status})
    except Exception as e:
        return _err(e)


@bp.post("/<sponsor_ulid>/mou")
def set_mou(sponsor_ulid: str):
    try:
        status = (
            (request.get_json(force=True).get("status") or "").strip().lower()
        )
        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_mou_status(
            sponsor_ulid=sponsor_ulid,
            status=status,
            request_id=req,
            actor_id=actor,
        )
        return _ok({"mou_status": status})
    except Exception as e:
        return _err(e)


@bp.post("/<sponsor_ulid>/pledges")
def upsert_pledge(sponsor_ulid: str):
    try:
        pledge = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        pid = sp_svc.upsert_pledge(
            sponsor_ulid=sponsor_ulid,
            pledge=pledge,
            request_id=req,
            actor_id=actor,
        )
        return _ok(
            {"pledge_ulid": pid, "sponsor": sp_svc.sponsor_view(sponsor_ulid)}
        )
    except Exception as e:
        return _err(e)


@bp.post("/pledges/<pledge_ulid>/status")
def set_pledge_status(pledge_ulid: str):
    try:
        status = (
            (request.get_json(force=True).get("status") or "").strip().lower()
        )
        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_pledge_status(
            pledge_ulid=pledge_ulid,
            status=status,
            request_id=req,
            actor_id=actor,
        )
        return _ok({"pledge_ulid": pledge_ulid, "status": status})
    except Exception as e:
        return _err(e)


@bp.get("")
def search_sponsors():
    try:
        any_param = request.args.get("any", "")
        readiness = [
            p.strip()
            for p in request.args.get("readiness", "").split(",")
            if p.strip()
        ] or None
        has_act = request.args.get("has_active_pledges")
        review = request.args.get("review")

        def _pairs(s):
            out = []
            for t in (s or "").split(","):
                t = t.strip()
                if "." in t:
                    d, k = t.split(".", 1)
                    out.append((d.strip(), k.strip()))
            return out

        any_of = _pairs(any_param)
        page = request.args.get("page", type=int, default=1)
        per = request.args.get("per", type=int, default=50)
        rows, total = sp_svc.find_sponsors(
            any_of=any_of or None,
            readiness_in=readiness,
            has_active_pledges=None
            if has_act is None
            else (has_act.lower() in ("1", "true", "yes")),
            admin_review_required=None
            if review is None
            else (review.lower() in ("1", "true", "yes")),
            page=page,
            per=per,
        )
        return _ok({"rows": rows, "total": total, "page": page, "per": per})
    except Exception as e:
        return _err(e)
