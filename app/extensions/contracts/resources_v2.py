# app/extensions/contracts/resources_v2.py
# -*- coding: utf-8 -*-
"""
resources_v2 — Stable, PII-free contract for the Resources slice.

This contract exposes typed functions used by other slices and CLIs.
Breaking changes must ship as resources_v3 (leave v2 in place).

Ethos:
- Skinny contract: validate inputs, call services, shape outputs.
- No slice reach-ins; all mutations emit ledger events within services.
- DTOs return names/ids only; no PII.

Functions:
  ensure_resource(entity_ulid, request_id, actor_ulid) ->
   {"resource_ulid": str}
  set_readiness(resource_ulid, status, request_id, actor_ulid) ->
   {"version_ptr": str|None}
  set_mou(resource_ulid, status, request_id, actor_ulid) ->
   {"version_ptr": str|None}
  upsert_capabilities(resource_ulid, capabilities, request_id, actor_ulid) ->
   {"history_ulid": str|None}
  patch_capabilities(resource_ulid, capabilities, request_id, actor_ulid) ->
   {"history_ulid": str|None}
  promote_if_clean(resource_ulid, request_id, actor_ulid) ->
   {"promoted": bool}
  rebuild_index(resource_ulid, request_id, actor_ulid) ->
   {"reindexed": int}
  rebuild_all(page, per, request_id, actor_ulid) ->
   {"processed": int, "page": int, "per": int}
  get_profile(resource_ulid) ->
   {"resource_ulid": str, "status": str, "mou_status": str, "capabilities": dict, ...}
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, TypedDict

from sqlalchemy.orm import Session

from app.extensions.contracts.entity_v2 import get_entity_card
from app.slices.resources import services as svc
from app.slices.resources.models import ResourcePOC

# ---------- classes ----------


class ResourceProfileDTO(TypedDict):
    resource_ulid: str
    status: str
    mou_status: str
    capabilities: dict


__schema__ = {
    "get_profile": {
        "requires": ["resource_ulid"],
        "returns_keys": [
            "resource_ulid",
            "status",
            "mou_status",
            "capabilities",
        ],
    }
}


# ---------- helpers ----------


def _ok(data: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": dict(data)}


def _one(key: str, value: Any) -> dict[str, Any]:
    return {"ok": True, "data": {key: value}}


# ---------- API ----------


def get_profile(resource_ulid: str) -> ResourceProfileDTO:
    return {
        "resource_ulid": resource_ulid,
        "status": "active",
        "mou_status": "none",
        "capabilities": {},
    }


def ensure_resource(
    *, entity_ulid: str, request_id: str, actor_ulid: Optional[str]
) -> dict:
    rid = svc.ensure_resource(
        entity_ulid=entity_ulid, request_id=request_id, actor_ulid=actor_ulid
    )
    return _one("resource_ulid", rid)


def set_readiness(
    *,
    resource_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    version_ptr = svc.set_readiness_status(
        resource_ulid=resource_ulid,
        status=status,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )
    return _one("version_ptr", version_ptr)


def set_mou(
    *,
    resource_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    version_ptr = svc.set_mou_status(
        resource_ulid=resource_ulid,
        status=status,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )
    return _one("version_ptr", version_ptr)


def upsert_capabilities(
    *,
    resource_ulid: str,
    capabilities: dict,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    hist = svc.upsert_capabilities(
        resource_ulid=resource_ulid,
        payload=capabilities,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )
    return _one("history_ulid", hist)


def patch_capabilities(
    *,
    resource_ulid: str,
    capabilities: dict,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    hist = svc.patch_capabilities(
        resource_ulid=resource_ulid,
        payload=capabilities,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )
    return _one("history_ulid", hist)


def promote_if_clean(
    *, resource_ulid: str, request_id: str, actor_ulid: Optional[str]
) -> dict:
    promoted = svc.promote_readiness_if_clean(
        resource_ulid=resource_ulid,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )
    return _one("promoted", promoted)


def rebuild_index(
    *, resource_ulid: str, request_id: str, actor_ulid: Optional[str]
) -> dict:
    n = svc.rebuild_capability_index(
        resource_ulid=resource_ulid,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )
    return _ok({"reindexed": int(n)})


def rebuild_all(
    *,
    page: int = 1,
    per: int = 50,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    processed = svc.rebuild_all_capability_indexes(
        page=page, per=per, request_id=request_id, actor_ulid=actor_ulid
    )
    return _ok(
        {"processed": int(processed), "page": int(page), "per": int(per)}
    )


# ---------------- Resource POC workings ----------------------


def get_org_poc_cards(sess: Session, org_ulid: str) -> list[dict]:
    rows = (
        sess.query(ResourcePOC)
        .filter(
            ResourcePOC.org_ulid == org_ulid, ResourcePOC.relation == "poc"
        )
        .order_by(
            ResourcePOC.active.desc(),
            ResourcePOC.scope.asc(),
            ResourcePOC.rank.asc(),
        )
        .all()
    )
    cards = []
    for r in rows:
        person = get_entity_card(sess, r.person_entity_ulid)
        cards.append(
            {
                "link": {
                    "org_ulid": r.org_ulid,
                    "person_entity_ulid": r.person_entity_ulid,
                    "relation": r.relation,
                    "scope": r.scope,
                    "rank": r.rank,
                    "is_primary": r.is_primary,
                    "org_role": r.org_role,
                    "valid_from_utc": r.valid_from_utc,
                    "valid_to_utc": r.valid_to_utc,
                    "active": r.active,
                },
                "person": person.__dict__,
            }
        )
    return cards
