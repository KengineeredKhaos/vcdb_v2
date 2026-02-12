"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResourceCapabilityView:
    domain: str
    key: str


@dataclass(frozen=True)
class ResourceView:
    resource_ulid: str
    entity_ulid: str
    admin_review_required: bool
    readiness_status: str
    mou_status: str
    active_capabilities: list[ResourceCapabilityView]
    capability_last_update_utc: str | None
    first_seen_utc: str | None
    last_touch_utc: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


@dataclass(frozen=True)
class ResourcePOCLinkView:
    resource_ulid: str
    person_entity_ulid: str
    relation: str
    scope: str | None
    rank: int | None
    is_primary: bool
    org_role: str | None
    valid_from_utc: str | None
    valid_to_utc: str | None
    active: bool


@dataclass(frozen=True)
class ResourcePOCView:
    link: ResourcePOCLinkView


def map_resource_capability(c) -> ResourceCapabilityView:
    return ResourceCapabilityView(
        domain=getattr(c, "domain", ""),
        key=getattr(c, "key", ""),
    )


def map_resource_view(r, active_caps: Sequence[object]) -> ResourceView:
    entity_ulid = getattr(r, "entity_ulid", "")
    return ResourceView(
        resource_ulid=entity_ulid,
        entity_ulid=entity_ulid,
        admin_review_required=bool(
            getattr(r, "admin_review_required", False)
        ),
        readiness_status=getattr(r, "readiness_status", ""),
        mou_status=getattr(r, "mou_status", ""),
        active_capabilities=[map_resource_capability(c) for c in active_caps],
        capability_last_update_utc=getattr(
            r, "capability_last_update_utc", None
        ),
        first_seen_utc=getattr(r, "first_seen_utc", None),
        last_touch_utc=getattr(r, "last_touch_utc", None),
        created_at_utc=getattr(r, "created_at_utc", None),
        updated_at_utc=getattr(r, "updated_at_utc", None),
    )


def map_resource_poc_view(d: Mapping[str, Any]) -> ResourcePOCView:
    link_raw = d.get("link", d)
    link = link_raw if isinstance(link_raw, Mapping) else {}
    return ResourcePOCView(
        link=ResourcePOCLinkView(
            resource_ulid=str(link.get("resource_ulid", "")),
            person_entity_ulid=str(link.get("person_entity_ulid", "")),
            relation=str(link.get("relation", "")),
            scope=link.get("scope", None),
            rank=link.get("rank", None),
            is_primary=bool(link.get("is_primary", False)),
            org_role=link.get("org_role", None),
            valid_from_utc=link.get("valid_from_utc", None),
            valid_to_utc=link.get("valid_to_utc", None),
            active=bool(link.get("active", False)),
        )
    )


def map_resource_poc_list(
    rows: Sequence[Mapping[str, Any]],
) -> list[ResourcePOCView]:
    return [map_resource_poc_view(r) for r in rows]


def resource_view_to_dto(view: ResourceView) -> dict[str, Any]:
    return {
        "resource_ulid": view.resource_ulid,
        "entity_ulid": view.entity_ulid,
        "admin_review_required": view.admin_review_required,
        "readiness_status": view.readiness_status,
        "mou_status": view.mou_status,
        "active_capabilities": [
            {"domain": c.domain, "key": c.key}
            for c in view.active_capabilities
        ],
        "capability_last_update_utc": view.capability_last_update_utc,
        "first_seen_utc": view.first_seen_utc,
        "last_touch_utc": view.last_touch_utc,
        "created_at_utc": view.created_at_utc,
        "updated_at_utc": view.updated_at_utc,
    }


def resource_poc_view_to_dto(view: ResourcePOCView) -> dict[str, Any]:
    link = view.link
    return {
        "link": {
            "resource_ulid": link.resource_ulid,
            "person_entity_ulid": link.person_entity_ulid,
            "relation": link.relation,
            "scope": link.scope,
            "rank": link.rank,
            "is_primary": link.is_primary,
            "org_role": link.org_role,
            "valid_from_utc": link.valid_from_utc,
            "valid_to_utc": link.valid_to_utc,
            "active": link.active,
        }
    }


def resource_poc_list_to_dto(
    views: Sequence[ResourcePOCView],
) -> list[dict[str, Any]]:
    return [resource_poc_view_to_dto(v) for v in views]


__all__ = [
    "ResourceCapabilityView",
    "ResourceView",
    "ResourcePOCLinkView",
    "ResourcePOCView",
    "map_resource_capability",
    "map_resource_view",
    "map_resource_poc_view",
    "map_resource_poc_list",
    "resource_view_to_dto",
    "resource_poc_view_to_dto",
    "resource_poc_list_to_dto",
]
