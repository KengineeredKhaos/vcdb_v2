# app/slices/auth/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.lib.request_ctx import ensure_request_id, get_actor_ulid
from app.lib.security import (
    require_rbac,  # if you want to gate routes; can be toggled
)
from app.slices.auth import services as auth_svc

bp = Blueprint("auth", __name__, url_prefix="/auth")

# ---- Helpers ---------------------------------------------------------------


def _json_ok(data=None, **extras):
    return jsonify({"ok": True, "data": data, **extras}), 200


def _json_err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


# ---- Users -----------------------------------------------------------------


@bp.get("/users")
# @require_rbac("auditor")  # example: list requires auditor or admin
def list_users():
    page = request.args.get("page", type=int, default=1)
    per = request.args.get("per", type=int, default=50)
    rows, total = auth_svc.list_users(page=page, per=per)
    return _json_ok({"rows": rows, "total": total, "page": page, "per": per})


@bp.get("/users/<user_ulid>")
# @require_rbac("user")
def get_user(user_ulid: str):
    view = auth_svc.user_view(user_ulid)
    if not view:
        return _json_err("not found", 404)
    return _json_ok(view)


@bp.post("/users")
# @require_rbac("admin")
def create_user():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req_id = ensure_request_id()
        actor = get_actor_ulid()

        user_ulid = auth_svc.create_user(
            username=payload.get("username", ""),
            password=payload.get("password", ""),
            email=payload.get("email"),
            entity_ulid=payload.get("entity_ulid"),
            request_id=req_id,
            actor_id=actor,
        )
        return _json_ok({"user_ulid": user_ulid})
    except Exception as e:
        return _json_err(e)


@bp.post("/users/<user_ulid>/password")
# @require_rbac("admin")
def set_password(user_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req_id = ensure_request_id()
        actor = get_actor_ulid()

        auth_svc.set_password(
            user_ulid=user_ulid,
            new_password=payload.get("new_password", ""),
            request_id=req_id,
            actor_id=actor,
        )
        return _json_ok()
    except Exception as e:
        return _json_err(e)


@bp.post("/users/<user_ulid>/active")
# @require_rbac("admin")
def toggle_active(user_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        active = bool(payload.get("active", True))
        req_id = ensure_request_id()
        actor = get_actor_ulid()

        auth_svc.toggle_active(
            user_ulid=user_ulid,
            active=active,
            request_id=req_id,
            actor_id=actor,
        )
        return _json_ok({"is_active": active})
    except Exception as e:
        return _json_err(e)


# ---- RBAC roles ------------------------------------------------------------


@bp.post("/users/<user_ulid>/roles")
# @require_rbac("admin")
def attach_role(user_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        role_code = (payload.get("role_code") or "").strip().lower()
        req_id = ensure_request_id()
        actor = get_actor_ulid()

        created = auth_svc.assign_role(
            user_ulid=user_ulid,
            role_code=role_code,
            request_id=req_id,
            actor_id=actor,
        )
        return _json_ok({"attached": created, "role_code": role_code})
    except Exception as e:
        return _json_err(e)


@bp.delete("/users/<user_ulid>/roles/<role_code>")
# @require_rbac("admin")
def detach_role(user_ulid: str, role_code: str):
    try:
        req_id = ensure_request_id()
        actor = get_actor_ulid()

        removed = auth_svc.remove_role(
            user_ulid=user_ulid,
            role_code=(role_code or "").lower(),
            request_id=req_id,
            actor_id=actor,
        )
        return _json_ok({"removed": removed, "role_code": role_code})
    except Exception as e:
        return _json_err(e)


# ---- AuthN (basic) ---------------------------------------------------------


@bp.post("/login")
def login_basic():
    """
    Simple credential check; session mgmt happens in your web layer if/when you add it.
    Returns user_ulid on success (no cookies here).
    """
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req_id = ensure_request_id()
        user_ulid = auth_svc.authenticate(
            username=payload.get("username", ""),
            password=payload.get("password", ""),
            request_id=req_id,
        )
        if not user_ulid:
            return _json_err("invalid credentials", 401)
        return _json_ok({"user_ulid": user_ulid})
    except Exception as e:
        return _json_err(e)
