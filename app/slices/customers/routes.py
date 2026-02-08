# app/slices/customers/routes.py
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from flask import jsonify, request

from app.extensions import db
from app.extensions.errors import ContractError
from app.lib.request_ctx import ensure_request_id, get_actor_ulid
from app.slices.entity.guards import require_person_entity_ulid

from . import bp


def _ok(*, request_id: str, data: Any = None, status: int = 200, **extra):
    payload = {"ok": True, "request_id": request_id, "data": data, **extra}
    return jsonify(payload), status


def _err(*, request_id: str, exc: Exception | str, code: int = 500):
    if isinstance(exc, ContractError):
        payload = {
            "ok": False,
            "request_id": request_id,
            "error": exc.message,
            "code": exc.code,
            "where": exc.where,
        }
        if getattr(exc, "data", None):
            payload["data"] = exc.data
        return jsonify(payload), exc.http_status

    if isinstance(exc, NotImplementedError):
        return (
            jsonify(
                {
                    "ok": False,
                    "request_id": request_id,
                    "error": "not implemented",
                }
            ),
            501,
        )
    if isinstance(exc, PermissionError):
        return (
            jsonify(
                {"ok": False, "request_id": request_id, "error": str(exc)}
            ),
            403,
        )
    if isinstance(exc, LookupError):
        return (
            jsonify(
                {"ok": False, "request_id": request_id, "error": str(exc)}
            ),
            404,
        )
    if isinstance(exc, ValueError):
        return (
            jsonify(
                {"ok": False, "request_id": request_id, "error": str(exc)}
            ),
            400,
        )

    return (
        jsonify({"ok": False, "request_id": request_id, "error": str(exc)}),
        code,
    )


def _dto_to_dict(dto: Any) -> Any:
    if dto is None:
        return None
    if isinstance(dto, dict):
        return dto
    if is_dataclass(dto):
        return asdict(dto)
    return dto


def _reject_legacy_keys(payload: dict[str, Any]) -> None:
    legacy: list[str] = []
    if "customer_ulid" in payload:
        legacy.append("customer_ulid")
    if "ulid" in payload:
        legacy.append("ulid")
    if legacy:
        raise ValueError(
            "legacy key(s) not allowed: "
            f"{', '.join(legacy)}; use entity_ulid"
        )


@bp.post("")
def create_customer():
    from . import services as cust_svc

    req = ensure_request_id()
    actor = get_actor_ulid()

    payload = request.get_json(force=True, silent=False) or {}
    try:
        _reject_legacy_keys(payload)

        entity_ulid = (payload.get("entity_ulid") or "").strip()
        if not entity_ulid:
            raise ValueError("entity_ulid is required")

        require_person_entity_ulid(
            db.session, entity_ulid, where="customers.routes.create_customer"
        )

        # NEW CANON: ensure_customer returns entity_ulid (str)
        ent = cust_svc.ensure_customer(
            entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )

        db.session.commit()
        return _ok(
            request_id=req,
            data={"entity_ulid": ent},
            status=201,
        )

    except Exception as exc:
        db.session.rollback()
        return _err(request_id=req, exc=exc)


@bp.get("/<entity_ulid>")
def view_customer(entity_ulid: str):
    from . import services as cust_svc

    req = ensure_request_id()
    try:
        dto = cust_svc.get_dashboard_view(entity_ulid=entity_ulid)
        if not dto:
            raise LookupError("not found")
        return _ok(request_id=req, data=_dto_to_dict(dto))
    except Exception as exc:
        return _err(request_id=req, exc=exc)


@bp.post("/<entity_ulid>/needs/<tier_key>")
def update_needs(entity_ulid: str, tier_key: str):
    from . import services as cust_svc

    req = ensure_request_id()
    actor = get_actor_ulid()
    payload = request.get_json(force=True, silent=False) or {}

    try:
        _reject_legacy_keys(payload)

        vptr = cust_svc.record_needs_tier(
            entity_ulid=entity_ulid,
            tier_key=tier_key,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )

        db.session.commit()
        return _ok(request_id=req, data={"version_ptr": vptr})

    except Exception as exc:
        db.session.rollback()
        return _err(request_id=req, exc=exc)


@bp.get("/<entity_ulid>/eligibility")
def get_eligibility(entity_ulid: str):
    from . import services as cust_svc

    req = ensure_request_id()
    try:
        dto = cust_svc.get_eligibility_snapshot(entity_ulid=entity_ulid)
        if not dto:
            raise LookupError("not found")
        return _ok(request_id=req, data=_dto_to_dict(dto))
    except Exception as exc:
        return _err(request_id=req, exc=exc)
