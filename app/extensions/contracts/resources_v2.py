# app/extensions/contracts/resources_v2.py
"""
resources_v2 — Stable contract for the Resources slice.

Ethos:
- Skinny contract: validate inputs, call services, shape outputs.
- No slice reach-ins; all mutations emit ledger events within services.
- DTOs are ULID + normalized keys only (capability domain/key), no notes.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.extensions.errors import ContractError
from app.slices.resources import mapper as res_mapper
from app.slices.resources import services as svc
from app.slices.resources import services_matching as match_svc


class ResourceFactsDTO(TypedDict, total=False):
    entity_ulid: str
    admin_review_required: bool
    readiness_status: str
    mou_status: str
    active_capability_keys: list[str]
    capability_last_update_utc: str | None


class ResourceProfileHintsDTO(TypedDict, total=False):
    entity_ulid: str
    service_area_note: str | None
    sla_note: str | None


class ResourceNeedMatchItemDTO(TypedDict, total=False):
    entity_ulid: str
    readiness_status: str
    mou_status: str
    matched_capability_keys: list[str]
    bucket: str
    reason_codes: list[str]


class ResourceNeedMatchResultDTO(TypedDict, total=False):
    customer_ulid: str
    need_key: str
    tier: int
    tier_priority: int | None
    customer_gate: str
    blocked_reason: str | None
    operator_cautions: list[str]
    exact_matches: list[ResourceNeedMatchItemDTO]
    adjacent_matches: list[ResourceNeedMatchItemDTO]
    review_matches: list[ResourceNeedMatchItemDTO]
    as_of_iso: str


__schema__ = {
    "get_resource_facts": {
        "requires": ["entity_ulid"],
        "returns_keys": [
            "entity_ulid",
            "admin_review_required",
            "readiness_status",
            "mou_status",
            "active_capability_keys",
            "capability_last_update_utc",
        ],
    },
    "get_resource_profile_hints": {
        "requires": ["entity_ulid"],
        "returns_keys": [
            "entity_ulid",
            "service_area_note",
            "sla_note",
        ],
    },
    "find_resources": {
        "requires": [],
        "returns_keys": ["items", "total", "page", "per"],
    },
    "match_customer_need": {
        "requires": ["customer_ulid", "need_key"],
        "returns_keys": [
            "customer_ulid",
            "need_key",
            "tier",
            "tier_priority",
            "customer_gate",
            "blocked_reason",
            "operator_cautions",
            "exact_matches",
            "adjacent_matches",
            "review_matches",
            "as_of_iso",
        ],
    },
}


# -----------------
# Contract Error
# Handling
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=str(exc),
            http_status=400,
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
    )


def get_resource_facts(*, entity_ulid: str) -> ResourceFactsDTO | None:
    where = "resources_v2.get_resource_facts"
    try:
        view = svc.resource_view(entity_ulid)
        if view is None:
            return None
        # You should implement this mapper to return flat keys and no notes.
        return res_mapper.resource_facts_to_contract_dto(view)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_resource_profile_hints(
    *, entity_ulid: str
) -> ResourceProfileHintsDTO | None:
    where = "resources_v2.get_resource_profile_hints"
    try:
        hints = svc.get_profile_hints(entity_ulid)
        return {
            "entity_ulid": entity_ulid,
            "service_area_note": hints.get("service_area_note"),
            "sla_note": hints.get("sla_note"),
        }
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def find_resources(
    *,
    any_of: list[tuple[str, str]] | None = None,
    all_of: list[tuple[str, str]] | None = None,
    admin_review_required: bool | None = None,
    readiness_in: list[str] | None = None,
    page: int = 1,
    per: int = 50,
) -> dict[str, Any]:
    where = "resources_v2.find_resources"
    try:
        rows, total = svc.find_resources(
            any_of=any_of,
            all_of=all_of,
            admin_review_required=admin_review_required,
            readiness_in=readiness_in,
            page=page,
            per=per,
        )
        return {
            "items": [
                res_mapper.resource_facts_to_contract_dto(v) for v in rows
            ],
            "total": total,
            "page": page,
            "per": per,
        }
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def _match_item_to_dto(
    item: match_svc.ResourceNeedMatchItemView,
) -> ResourceNeedMatchItemDTO:
    return {
        "entity_ulid": item.entity_ulid,
        "readiness_status": item.readiness_status,
        "mou_status": item.mou_status,
        "matched_capability_keys": list(item.matched_capability_keys),
        "bucket": item.bucket,
        "reason_codes": list(item.reason_codes),
    }


def match_customer_need(
    *,
    customer_ulid: str,
    need_key: str,
    include_adjacent: bool = True,
) -> ResourceNeedMatchResultDTO:
    where = "resources_v2.match_customer_need"
    try:
        view = match_svc.match_customer_need(
            customer_ulid=customer_ulid,
            need_key=need_key,
            include_adjacent=include_adjacent,
        )
        return {
            "customer_ulid": view.customer_ulid,
            "need_key": view.need_key,
            "tier": view.tier,
            "tier_priority": view.tier_priority,
            "customer_gate": view.customer_gate,
            "blocked_reason": view.blocked_reason,
            "operator_cautions": list(view.operator_cautions),
            "exact_matches": [
                _match_item_to_dto(v) for v in view.exact_matches
            ],
            "adjacent_matches": [
                _match_item_to_dto(v) for v in view.adjacent_matches
            ],
            "review_matches": [
                _match_item_to_dto(v) for v in view.review_matches
            ],
            "as_of_iso": view.as_of_iso,
        }
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def ensure_resource(
    *, entity_ulid: str, request_id: str, actor_ulid: str | None
) -> str:
    where = "resources_v2.ensure_resource"
    try:
        return svc.ensure_resource(
            resource_entity_ulid=entity_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


__all__ = [
    "get_resource_facts",
    "get_resource_profile_hints",
    "ensure_resource",
    "find_resources",
    "match_customer_need",
]
