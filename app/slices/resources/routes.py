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

# app/slices/resources/routes.py

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, url_for

from app.extensions import db
from app.lib.request_ctx import get_actor_ulid, get_request_id
from app.lib.security import require_permission

from . import mapper as res_mapper
from . import services as res_svc
from . import taxonomy as tax

bp = Blueprint(
    "resources",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/resources",
)


def _ok(*, request_id: str, data: object = None, meta: dict | None = None):
    out = {"ok": True, "request_id": request_id}
    if data is not None:
        out["data"] = data
    if meta is not None:
        out["meta"] = meta
    return jsonify(out), 200


def _err(*, request_id: str, exc: Exception, status: int | None = None):
    if isinstance(exc, ValueError):
        return (
            jsonify(
                {
                    "ok": False,
                    "request_id": request_id,
                    "error": {
                        "code": "bad_argument",
                        "message": str(exc),
                    },
                }
            ),
            status or 400,
        )
    return (
        jsonify(
            {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "internal_error",
                    "message": str(exc),
                },
            }
        ),
        status or 500,
    )


# -----------------
# search/view
# get-only routes
# -----------------


@bp.get("/search")
# @require_permission("resources:read")
def search_resources():
    req = get_request_id()
    if (
        request.accept_mimetypes.accept_html
        and request.args.get("format") != "json"
    ):
        return render_template(
            "resources/search.html",
            api_search_url=url_for("resources.search_resources"),
            api_ensure_url=url_for("resources.ensure_resource"),
        )
    try:
        page = int(request.args.get("page", "1") or "1")
        per = int(request.args.get("per", "50") or "50")

        # (Optional) policy-driven filters can be added later.
        rows, total = res_svc.find_resources(page=page, per=per)

        return _ok(
            request_id=req,
            data=[res_mapper.resource_view_to_dto(v) for v in rows],
            meta={"total": total, "page": page, "per": per},
        )
    except Exception as exc:
        return _err(request_id=req, exc=exc)


@bp.get("/<entity_ulid>")
# @require_permission("resources:read")
def get_resource(entity_ulid: str):
    req = get_request_id()
    try:
        view = res_svc.resource_view(entity_ulid)
        if view is None:
            return _err(
                request_id=req, exc=ValueError("not found"), status=404
            )
        return _ok(request_id=req, data=res_mapper.resource_view_to_dto(view))
    except Exception as exc:
        return _err(request_id=req, exc=exc)


@bp.get("/<entity_ulid>/profile-hints")
# @require_permission("resources:read")
def get_profile_hints(entity_ulid: str):
    req = get_request_id()
    if (
        request.accept_mimetypes.accept_html
        and request.args.get("format") != "json"
    ):
        return render_template(
            "resources/resource.html",
            entity_ulid=entity_ulid,
            readiness_states=list(tax.RESOURCE_READINESS_STATES),
            mou_statuses=list(tax.RESOURCE_MOU_STATUSES),
        )
    try:
        hints = res_svc.get_profile_hints(entity_ulid)
        return _ok(request_id=req, data=hints)
    except Exception as exc:
        return _err(request_id=req, exc=exc)


@bp.get("/<entity_ulid>/pocs-expanded")
# @require_permission("resources:read")
def get_pocs_expanded(entity_ulid: str):
    req = get_request_id()
    actor = get_actor_ulid()
    try:
        data = res_svc.resource_list_pocs_expanded(
            resource_entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        return _ok(request_id=req, data=data)
    except Exception as exc:
        return _err(request_id=req, exc=exc)


# ----------------
# Edit Routes
# ----------------


@bp.post("/ensure")
# @require_permission("resources:write")
def ensure_resource():
    req = get_request_id()
    actor = get_actor_ulid()
    try:
        payload = request.get_json(force=True, silent=False) or {}
        entity_ulid = (payload.get("entity_ulid") or "").strip()
        if not entity_ulid:
            raise ValueError("entity_ulid is required")

        rid = res_svc.ensure_resource(
            resource_entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            request_id=req,
            data={"resource_entity_ulid": rid},
        )
    except Exception as exc:
        db.session.rollback()
        return _err(request_id=req, exc=exc)


@bp.post("/<entity_ulid>/capabilities")
# @require_permission("resources:write")
def upsert_capabilities(entity_ulid: str):
    req = get_request_id()
    actor = get_actor_ulid()
    try:
        payload = request.get_json(force=True, silent=False) or {}
        hist_ulid = res_svc.upsert_capabilities(
            resource_entity_ulid=entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()

        view = res_svc.resource_view(entity_ulid)
        return _ok(
            request_id=req,
            data={
                "changed": hist_ulid is not None,
                "history_ulid": hist_ulid,
                "view": None
                if view is None
                else res_mapper.resource_view_to_dto(view),
            },
        )
    except Exception as exc:
        db.session.rollback()
        return _err(request_id=req, exc=exc)


@bp.post("/<entity_ulid>/profile-hints")
# @require_permission("resources:write")
def set_profile_hints(entity_ulid: str):
    req = get_request_id()
    actor = get_actor_ulid()
    try:
        payload = request.get_json(force=True, silent=False) or {}
        hist_ulid = res_svc.set_profile_hints(
            resource_entity_ulid=entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()

        view = res_svc.resource_view(entity_ulid)
        return _ok(
            request_id=req,
            data={
                "changed": hist_ulid is not None,
                "history_ulid": hist_ulid,
                "view": None
                if view is None
                else res_mapper.resource_view_to_dto(view),
            },
        )
    except Exception as exc:
        db.session.rollback()
        return _err(request_id=req, exc=exc)


@bp.post("/<entity_ulid>/status/readiness")
# @require_permission("resources:write")
def set_readiness(entity_ulid: str):
    req = get_request_id()
    actor = get_actor_ulid()
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip()

        res_svc.set_readiness_status(
            resource_entity_ulid=entity_ulid,
            to_status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(request_id=req)
    except Exception as exc:
        db.session.rollback()
        return _err(request_id=req, exc=exc)


@bp.post("/<entity_ulid>/status/mou")
# @require_permission("resources:write")
def set_mou(entity_ulid: str):
    req = get_request_id()
    actor = get_actor_ulid()
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip()

        res_svc.set_mou_status(
            resource_entity_ulid=entity_ulid,
            to_status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(request_id=req)
    except Exception as exc:
        db.session.rollback()
        return _err(request_id=req, exc=exc)
