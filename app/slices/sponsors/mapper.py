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
class SponsorCapabilityView:
    domain: str
    key: str


@dataclass(frozen=True)
class SponsorPledgeView:
    pledge_ulid: str
    type: str
    status: str
    has_restriction: bool
    est_value_number: int | None
    currency: str | None
    updated_at_utc: str | None


@dataclass(frozen=True)
class SponsorView:
    sponsor_ulid: str
    entity_ulid: str
    admin_review_required: bool
    readiness_status: str
    mou_status: str
    active_capabilities: list[SponsorCapabilityView]
    pledges: list[SponsorPledgeView]
    capability_last_update_utc: str | None
    pledge_last_update_utc: str | None
    first_seen_utc: str | None
    last_touch_utc: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


@dataclass(frozen=True)
class SponsorPOCLinkView:
    sponsor_ulid: str
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
class SponsorPOCView:
    link: SponsorPOCLinkView


def map_sponsor_capability(c) -> SponsorCapabilityView:
    return SponsorCapabilityView(
        domain=getattr(c, "domain", ""),
        key=getattr(c, "key", ""),
    )


def map_sponsor_pledge(p) -> SponsorPledgeView:
    return SponsorPledgeView(
        pledge_ulid=getattr(p, "pledge_ulid", ""),
        type=getattr(p, "type", ""),
        status=getattr(p, "status", ""),
        has_restriction=bool(getattr(p, "has_restriction", False)),
        est_value_number=getattr(p, "est_value_number", None),
        currency=getattr(p, "currency", None),
        updated_at_utc=getattr(p, "updated_at_utc", None),
    )


def map_sponsor_view(
    s,
    active_caps: Sequence[object],
    pledges: Sequence[object],
) -> SponsorView:
    entity_ulid = getattr(s, "entity_ulid", "")
    return SponsorView(
        sponsor_ulid=entity_ulid,
        entity_ulid=entity_ulid,
        admin_review_required=bool(
            getattr(s, "admin_review_required", False)
        ),
        readiness_status=getattr(s, "readiness_status", ""),
        mou_status=getattr(s, "mou_status", ""),
        active_capabilities=[map_sponsor_capability(c) for c in active_caps],
        pledges=[map_sponsor_pledge(p) for p in pledges],
        capability_last_update_utc=getattr(
            s, "capability_last_update_utc", None
        ),
        pledge_last_update_utc=getattr(s, "pledge_last_update_utc", None),
        first_seen_utc=getattr(s, "first_seen_utc", None),
        last_touch_utc=getattr(s, "last_touch_utc", None),
        created_at_utc=getattr(s, "created_at_utc", None),
        updated_at_utc=getattr(s, "updated_at_utc", None),
    )


def map_sponsor_poc_view(d: Mapping[str, Any]) -> SponsorPOCView:
    link_raw = d.get("link", d)
    link = link_raw if isinstance(link_raw, Mapping) else {}
    return SponsorPOCView(
        link=SponsorPOCLinkView(
            sponsor_ulid=str(link.get("sponsor_ulid", "")),
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


def map_sponsor_poc_list(
    rows: Sequence[Mapping[str, Any]],
) -> list[SponsorPOCView]:
    return [map_sponsor_poc_view(r) for r in rows]


def sponsor_view_to_dto(view: SponsorView) -> dict[str, Any]:
    return {
        "sponsor_ulid": view.sponsor_ulid,
        "entity_ulid": view.entity_ulid,
        "admin_review_required": view.admin_review_required,
        "readiness_status": view.readiness_status,
        "mou_status": view.mou_status,
        "active_capabilities": [
            {"domain": c.domain, "key": c.key}
            for c in view.active_capabilities
        ],
        "pledges": [
            {
                "pledge_ulid": p.pledge_ulid,
                "type": p.type,
                "status": p.status,
                "has_restriction": p.has_restriction,
                "est_value_number": p.est_value_number,
                "currency": p.currency,
                "updated_at_utc": p.updated_at_utc,
            }
            for p in view.pledges
        ],
        "capability_last_update_utc": view.capability_last_update_utc,
        "pledge_last_update_utc": view.pledge_last_update_utc,
        "first_seen_utc": view.first_seen_utc,
        "last_touch_utc": view.last_touch_utc,
        "created_at_utc": view.created_at_utc,
        "updated_at_utc": view.updated_at_utc,
    }


def sponsor_poc_view_to_dto(view: SponsorPOCView) -> dict[str, Any]:
    l = view.link
    return {
        "link": {
            "sponsor_ulid": l.sponsor_ulid,
            "person_entity_ulid": l.person_entity_ulid,
            "relation": l.relation,
            "scope": l.scope,
            "rank": l.rank,
            "is_primary": l.is_primary,
            "org_role": l.org_role,
            "valid_from_utc": l.valid_from_utc,
            "valid_to_utc": l.valid_to_utc,
            "active": l.active,
        }
    }


def sponsor_poc_list_to_dto(
    views: Sequence[SponsorPOCView],
) -> list[dict[str, Any]]:
    return [sponsor_poc_view_to_dto(v) for v in views]


__all__ = [
    "SponsorCapabilityView",
    "SponsorPledgeView",
    "SponsorView",
    "SponsorPOCLinkView",
    "SponsorPOCView",
    "map_sponsor_capability",
    "map_sponsor_pledge",
    "map_sponsor_view",
    "map_sponsor_poc_view",
    "map_sponsor_poc_list",
    "sponsor_view_to_dto",
    "sponsor_poc_view_to_dto",
    "sponsor_poc_list_to_dto",
]
