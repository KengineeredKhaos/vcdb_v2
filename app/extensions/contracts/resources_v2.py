# app/extensions/contracts/resources_v2.py
"""
resources_v2 — Stable contract for the Resources slice.

Ethos:
- Skinny contract: validate inputs, call services, shape outputs.
- No slice reach-ins; all mutations emit ledger events within services.
- DTOs are ULID + normalized keys only (capability domain/key), no notes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from app.extensions.errors import ContractError
from app.slices.resources import mapper as res_mapper
from app.slices.resources import services as svc
from app.slices.resources.models import ResourcePOC


class ResourceViewDTO(TypedDict, total=False):
    resource_ulid: str
    entity_ulid: str
    admin_review_required: bool
    readiness_status: str
    mou_status: str
    active_capabilities: list[dict]
    capability_last_update_utc: str | None
    first_seen_utc: str | None
    last_touch_utc: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


__schema__ = {
    "get_resource_view": {
        "requires": ["resource_ulid"],
        "returns_keys": [
            "resource_ulid",
            "entity_ulid",
            "admin_review_required",
            "readiness_status",
            "mou_status",
            "active_capabilities",
        ],
    }
}


def _ok(data: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": dict(data)}


def _one(key: str, value: Any) -> dict[str, Any]:
    return {"ok": True, "data": {key: value}}


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument", where=where, message=msg, http_status=400
        )
    if isinstance(exc, PermissionError):
        return ContractError(
            code="permission_denied",
            where=where,
            message=msg,
            http_status=403,
        )
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found", where=where, message=msg, http_status=404
        )

    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in resources contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


def get_resource_view(resource_ulid: str) -> ResourceViewDTO:
    where = "resources_v2.get_resource_view"
    try:
        view = svc.resource_view(resource_ulid)
        if not view:
            raise LookupError("resource not found")
        return res_mapper.resource_view_to_dto(view)
    except Exception as exc:
        raise _as_contract_error(where, exc)


def ensure_resource(
    *, entity_ulid: str, request_id: str, actor_ulid: str | None
) -> dict:
    where = "resources_v2.ensure_resource"
    try:
        rid = svc.ensure_resource(
            entity_ulid=entity_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _one("resource_ulid", rid)
    except Exception as exc:
        raise _as_contract_error(where, exc)


def set_readiness(
    *,
    resource_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: str | None,
) -> dict:
    where = "resources_v2.set_readiness"
    try:
        svc.set_readiness_status(
            resource_ulid=resource_ulid,
            status=status,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _ok(
            {"resource_ulid": resource_ulid, "readiness_status": status}
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)


def set_mou(
    *,
    resource_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: str | None,
) -> dict:
    where = "resources_v2.set_mou"
    try:
        svc.set_mou_status(
            resource_ulid=resource_ulid,
            status=status,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _ok({"resource_ulid": resource_ulid, "mou_status": status})
    except Exception as exc:
        raise _as_contract_error(where, exc)


def upsert_capabilities(
    *,
    resource_ulid: str,
    capabilities: dict,
    request_id: str,
    actor_ulid: str | None,
) -> dict:
    where = "resources_v2.upsert_capabilities"
    try:
        hist = svc.upsert_capabilities(
            resource_ulid=resource_ulid,
            payload=capabilities,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _one("history_ulid", hist or None)
    except Exception as exc:
        raise _as_contract_error(where, exc)


def patch_capabilities(
    *,
    resource_ulid: str,
    capabilities: dict,
    request_id: str,
    actor_ulid: str | None,
) -> dict:
    where = "resources_v2.patch_capabilities"
    try:
        hist = svc.patch_capabilities(
            resource_ulid=resource_ulid,
            payload=capabilities,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _one("history_ulid", hist or None)
    except Exception as exc:
        raise _as_contract_error(where, exc)


def promote_if_clean(
    *, resource_ulid: str, request_id: str, actor_ulid: str | None
) -> dict:
    where = "resources_v2.promote_if_clean"
    try:
        promoted = svc.promote_readiness_if_clean(
            resource_ulid=resource_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _one("promoted", bool(promoted))
    except Exception as exc:
        raise _as_contract_error(where, exc)


def rebuild_index(
    *, resource_ulid: str, request_id: str, actor_ulid: str | None
) -> dict:
    where = "resources_v2.rebuild_index"
    try:
        n = svc.rebuild_capability_index(
            resource_ulid=resource_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _ok({"reindexed": int(n)})
    except Exception as exc:
        raise _as_contract_error(where, exc)


def rebuild_all(
    *, page: int = 1, per: int = 200, request_id: str, actor_ulid: str | None
) -> dict:
    where = "resources_v2.rebuild_all"
    try:
        summary = svc.rebuild_all_capability_indexes(
            page=page, per=per, request_id=request_id, actor_ulid=actor_ulid
        )
        return _ok(summary)
    except Exception as exc:
        raise _as_contract_error(where, exc)


# ------------- Optional helper: list POCs (PII-free) -------------


def list_pocs(resource_ulid: str) -> list[dict]:
    """
    PII-free list of POC link rows (ULIDs + metadata only).
    If callers want names/emails/phones, they should fetch from Entity via entity_v2.
    """
    where = "resources_v2.list_pocs"
    try:
        views = svc.resource_list_pocs(resource_ulid=resource_ulid)
        return res_mapper.resource_poc_list_to_dto(views)
    except Exception as exc:
        raise _as_contract_error(where, exc)


# Back-compat for any accidental import; fix the broken function signature/columns.
def get_org_poc_cards(sess: Session, org_ulid: str) -> list[dict]:
    """
    Deprecated. Use list_pocs(resource_ulid) instead.
    Kept only so older dev experiments don't crash imports.
    """
    rows = (
        sess.query(ResourcePOC)
        .filter(
            ResourcePOC.resource_ulid == org_ulid,
            ResourcePOC.relation == "poc",
        )
        .order_by(
            ResourcePOC.active.desc(),
            ResourcePOC.scope.asc(),
            ResourcePOC.rank.asc(),
        )
        .all()
    )
    return [
        {
            "link": {
                "resource_ulid": r.resource_ulid,
                "person_entity_ulid": r.person_entity_ulid,
                "relation": r.relation,
                "scope": r.scope,
                "rank": r.rank,
                "is_primary": r.is_primary,
                "org_role": r.org_role,
                "valid_from_utc": r.valid_from_utc,
                "valid_to_utc": r.valid_to_utc,
                "active": r.active,
            }
        }
        for r in rows
    ]


__all__ = [
    "get_resource_view",
    "ensure_resource",
    "set_readiness",
    "set_mou",
    "upsert_capabilities",
    "patch_capabilities",
    "promote_if_clean",
    "rebuild_index",
    "rebuild_all",
    "list_pocs",
    "get_org_poc_cards",
]
