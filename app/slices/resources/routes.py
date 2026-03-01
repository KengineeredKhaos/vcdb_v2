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

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.extensions import db
from app.lib.request_ctx import get_actor_ulid, get_request_id

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

# -----------------
# Helpers
# -----------------


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


def _wants_json() -> bool:
    fmt = (request.args.get("format") or "").strip().lower()
    if fmt == "json":
        return True
    if fmt == "html":
        return False
    # Default: browsers get HTML
    if request.accept_mimetypes.accept_html:
        return False
    return True


def _split_codes(raw_items: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw_items or []:
        if not item:
            continue
        for part in str(item).split(","):
            s = part.strip()
            if s:
                out.append(s)
    return out


def _parse_domain_keys(raw_items: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in _split_codes(raw_items):
        if "." not in s:
            continue
        dom, key = s.split(".", 1)
        dom = dom.strip()
        key = key.strip()
        if dom and key:
            out.append((dom, key))
    return out


def _as_bool(v: str | None) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f"):
        return False
    return None


# -----------------
# Landing Page
# -----------------


@bp.get("/")
# @require_permission("resources:read")
def resources_index():
    return redirect(url_for("resources.search_resources"))


# -----------------
# search/view
# get-only routes
# -----------------


@bp.get("/search")
# @require_permission("resources:read")
def search_resources():
    req = get_request_id()
    try:
        page = int(request.args.get("page", "1") or "1")
        per = int(request.args.get("per", "50") or "50")

        any_of = _parse_domain_keys(request.args.getlist("any"))
        all_of = _parse_domain_keys(request.args.getlist("all"))
        readiness_in = _split_codes(request.args.getlist("readiness"))
        admin_review_required = _as_bool(
            request.args.get("admin_review_required")
        )
        onboard_step = (request.args.get("onboard_step") or "").strip()
        onboard_step = onboard_step.lower() if onboard_step else None

        rows, total = res_svc.find_resources(
            any_of=any_of or None,
            all_of=all_of or None,
            admin_review_required=admin_review_required,
            readiness_in=readiness_in or None,
            onboard_step=onboard_step,
            page=page,
            per=per,
        )

        dtos = [res_mapper.resource_view_to_dto(v) for v in rows]
        meta = {"total": total, "page": page, "per": per}

        if _wants_json():
            return _ok(request_id=req, data=dtos, meta=meta)

        # HTML
        from . import taxonomy as tax

        return render_template(
            "resources/search.html",
            request_id=req,
            items=dtos,
            meta=meta,
            form={
                "any": ",".join(f"{d}.{k}" for d, k in any_of),
                "all": ",".join(f"{d}.{k}" for d, k in all_of),
                "readiness": ",".join(readiness_in),
                "onboard_step": onboard_step or "",
                "admin_review_required": request.args.get(
                    "admin_review_required"
                )
                or "",
                "page": page,
                "per": per,
            },
            capability_codes=tax.all_capability_codes(),
            readiness_states=list(tax.RESOURCE_READINESS_STATES),
        )
    except Exception as exc:
        if _wants_json():
            return _err(request_id=req, exc=exc)
        return (
            render_template(
                "resources/search.html",
                request_id=req,
                items=[],
                meta={"total": 0, "page": 1, "per": 50},
                form={},
                capability_codes=[],
                readiness_states=[],
                error=str(exc),
            ),
            400,
        )


@bp.get("/<entity_ulid>")
# @require_permission("resources:read")
def get_resource(entity_ulid: str):
    req = get_request_id()
    try:
        view = res_svc.resource_view(entity_ulid)
        if view is None:
            if _wants_json():
                return _err(
                    request_id=req, exc=ValueError("not found"), status=404
                )
            return (
                render_template(
                    "resources/resource.html",
                    request_id=req,
                    entity_ulid=entity_ulid,
                    view=None,
                    error="not found",
                    readiness_states=[],
                    mou_statuses=[],
                    capability_codes=[],
                ),
                404,
            )

        dto = res_mapper.resource_view_to_dto(view)

        if _wants_json():
            return _ok(request_id=req, data=dto)

        from . import taxonomy as tax

        return render_template(
            "resources/resource.html",
            request_id=req,
            entity_ulid=entity_ulid,
            view=dto,
            readiness_states=list(tax.RESOURCE_READINESS_STATES),
            mou_statuses=list(tax.RESOURCE_MOU_STATUSES),
            capability_codes=tax.all_capability_codes(),
        )
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
