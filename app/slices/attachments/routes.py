# app/slices/attachments/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request
from werkzeug.datastructures import FileStorage

from app.lib.request_ctx import ensure_request_id, get_actor_ulid

from . import services as att_svc

bp = Blueprint("attachments", __name__, url_prefix="/attachments")


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra}), 200


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


@bp.post("/upload")
def upload():
    try:
        # Accept multipart/form-data (file field 'file')
        if "file" not in request.files:
            return _err("missing file")
        f: FileStorage = request.files["file"]
        mime = f.mimetype or "application/octet-stream"
        req = ensure_request_id()
        actor = get_actor_ulid()
        ulid = att_svc.upload_register(
            file_stream=f.stream,
            mime=mime,
            original_filename=f.filename,
            privacy_level=request.form.get("privacy_level", "A"),
            retention_policy_code=request.form.get("retention_policy_code"),
            request_id=req,
            actor_ulid=actor,
        )
        return _ok({"attachment_ulid": ulid})
    except Exception as e:
        return _err(e)


@bp.post("/link")
def link():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        link_ulid = att_svc.link_attachment(
            attachment_ulid=payload["attachment_ulid"],
            slice_name=payload["slice"],
            domain=payload["domain"],
            target_ulid=payload["target_ulid"],
            note=payload.get("note"),
            request_id=req,
            actor_ulid=actor,
        )
        return _ok({"link_ulid": link_ulid})
    except Exception as e:
        return _err(e)


@bp.post("/unlink")
def unlink():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        att_svc.unlink_attachment(
            link_ulid=payload["link_ulid"], request_id=req, actor_ulid=actor
        )
        return _ok()
    except Exception as e:
        return _err(e)


@bp.post("/sign-url")
def sign_url():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req = ensure_request_id()
        actor = get_actor_ulid()
        url = att_svc.sign_url(
            attachment_ulid=payload["attachment_ulid"],
            ttl_seconds=int(payload.get("ttl_seconds", 300)),
            request_id=req,
            actor_ulid=actor,
        )
        return _ok({"url": url})
    except Exception as e:
        return _err(e)
