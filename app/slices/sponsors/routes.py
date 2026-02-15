# app/slices/sponsors/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, redirect, request, url_for

from app.extensions import db
from app.extensions.contracts import sponsors_v2
from app.extensions.errors import ContractError
from app.lib.request_ctx import ensure_request_id, get_actor_ulid

from . import services as sp_svc

bp = Blueprint(
    "sponsors",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/sponsors",
)


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


# -----------------
# Wizard Routes
# -----------------


@bp.get("/onboard/start/<entity_ulid>")
def onboard_start(entity_ulid: str):
    sponsors_v2.ensure_sponsor_facet(entity_ulid=entity_ulid)
    return redirect(url_for("sponsors.onboard_step", entity_ulid=entity_ulid))


# -----------------
# Other Stuff
# -----------------


@bp.post("")
def ensure_sponsor():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        entity_ulid = (payload.get("entity_ulid") or "").strip()
        if not entity_ulid:
            return _err(ValueError("entity_ulid is required"), 400)
        req, actor = ensure_request_id(), get_actor_ulid()
        sponsor_entity_ulid = sp_svc.ensure_sponsor(
            sponsor_entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {"sponsor_entity_ulid": sponsor_entity_ulid}, request_id=req
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.get("/<sponsor_entity_ulid>")
def get_sponsor(sponsor_entity_ulid: str):
    dto = sp_svc.sponsor_view(sponsor_entity_ulid)
    return (
        _ok(dto, request_id=ensure_request_id())
        if dto
        else _err(LookupError("not found"), 404)
    )


@bp.post("/<sponsor_entity_ulid>/capabilities")
def upsert_caps(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        hist = sp_svc.upsert_capabilities(
            sponsor_entity_ulid=sponsor_entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {
                "history_ulid": hist,
                "sponsor": sp_svc.sponsor_view(sponsor_entity_ulid),
            },
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.patch("/<sponsor_entity_ulid>/capabilities")
def patch_caps(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        hist = sp_svc.patch_capabilities(
            sponsor_entity_ulid=sponsor_entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {
                "history_ulid": hist,
                "sponsor": sp_svc.sponsor_view(sponsor_entity_ulid),
            },
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.post("/<sponsor_entity_ulid>/readiness")
def set_readiness(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()
        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_readiness_status(
            sponsor_entity_ulid=sponsor_entity_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"readiness_status": status}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.post("/<sponsor_entity_ulid>/mou")
def set_mou(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()
        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_mou_status(
            sponsor_entity_ulid=sponsor_entity_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"mou_status": status}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.post("/<sponsor_entity_ulid>/pledges")
def upsert_pledge(sponsor_entity_ulid: str):
    try:
        pledge = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        pid = sp_svc.upsert_pledge(
            sponsor_entity_ulid=sponsor_entity_ulid,
            pledge=pledge,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {
                "pledge_ulid": pid,
                "sponsor": sp_svc.sponsor_view(sponsor_entity_ulid),
            },
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.post("/pledges/<pledge_ulid>/status")
def set_pledge_status(pledge_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()

        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_pledge_status(
            pledge_ulid=pledge_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {"pledge_ulid": pledge_ulid, "status": status}, request_id=req
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


@bp.get("")
def search_sponsors():
    req = ensure_request_id()
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
            has_active_pledges=(
                None
                if has_act is None
                else (has_act.lower() in ("1", "true", "yes"))
            ),
            admin_review_required=(
                None
                if review is None
                else (review.lower() in ("1", "true", "yes"))
            ),
            page=page,
            per=per,
        )
        return _ok(
            {"rows": rows, "total": total, "page": page, "per": per},
            request_id=req,
        )
    except Exception as e:
        return _err(e, 400)
