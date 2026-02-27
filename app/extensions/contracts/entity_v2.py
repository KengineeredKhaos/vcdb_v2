# app/extensions/contracts/entity_v2.py

from __future__ import annotations

from app.extensions.errors import ContractError
from app.slices.entity import guards as ent_guards
from app.slices.entity import services as ent_services
from app.slices.entity.mapper import (
    EntityAddressSummaryDTO,
    EntityCardDTO,
    EntityContactSummaryDTO,
    EntityLabelDTO,
    OrgView,
    PersonView,
)

# -----------------
# Contract Error
# Handlers
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
        return ContractError("permission_denied", where, msg, 403)
    if isinstance(exc, LookupError):
        return ContractError("not_found", where, msg, 404)
    return ContractError(
        code="internal_error",
        where=where,
        message=f"unexpected: {exc.__class__.__name__}",
        http_status=500,
    )


# -----------------
# Guards and Fills
# -----------------


def require_person_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
    where: str | None = None,
) -> str:
    err_where = where or "entity_v2.require_person_entity_ulid"
    try:
        return ent_guards.require_person_entity_ulid(
            entity_ulid,
            allow_archived=allow_archived,
        )
    except Exception as exc:
        raise _as_contract_error(err_where, exc) from exc


def require_org_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
    where: str | None = None,
) -> str:
    err_where = where or "entity_v2.require_org_entity_ulid"
    try:
        return ent_guards.require_org_entity_ulid(
            entity_ulid,
            allow_archived=allow_archived,
        )
    except Exception as exc:
        raise _as_contract_error(err_where, exc) from exc


# -----------------
# DTO's
# -----------------

# See Entity Mapper for DTO's


# -----------------
# Entity Data
# Edit/Update
# -----------------


# -----------------
# Summary Views
# -----------------


def get_person_view(entity_ulid: str) -> PersonView:
    where = "entity_v2.get_person_view"
    try:
        # Guard: must be a person entity.
        ent_guards.require_person_entity_ulid(entity_ulid)
        v = ent_services.get_person_view(entity_ulid=entity_ulid)
        if v is None:
            raise LookupError("person not found")
        return v
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_org_view(entity_ulid: str) -> OrgView:
    where = "entity_v2.get_org_view"
    try:
        # Guard: must be an org entity.
        ent_guards.require_org_entity_ulid(entity_ulid)
        v = ent_services.get_org_view(entity_ulid=entity_ulid)
        if v is None:
            raise LookupError("org not found")
        return v
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Cross-slice labels
# -----------------


def get_entity_labels(entity_ulids: list[str]) -> dict[str, EntityLabelDTO]:
    where = "entity_v2.get_entity_labels"
    try:
        return ent_services.get_entity_labels(entity_ulids=entity_ulids)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_entity_label(entity_ulid: str) -> EntityLabelDTO:
    where = "entity_v2.get_entity_label"
    try:
        d = ent_services.get_entity_labels(entity_ulids=[entity_ulid])
        v = d.get(entity_ulid)
        if v is None:
            raise LookupError("entity not found")
        return v
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_entity_contact_summary(
    *, entity_ulids: list[str]
) -> dict[str, EntityContactSummaryDTO]:
    where = "entity_v2.get_entity_contact_summary"
    try:
        return ent_services.get_entity_contact_summary(
            entity_ulids=entity_ulids
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_entity_address_summary(
    *, entity_ulids: list[str]
) -> dict[str, EntityAddressSummaryDTO]:
    where = "entity_v2.get_entity_address_summary"
    try:
        return ent_services.get_entity_address_summary(
            entity_ulids=entity_ulids
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_entity_cards(
    *,
    entity_ulids: list[str],
    include_contacts: bool = False,
    include_addresses: bool = False,
) -> dict[str, EntityCardDTO]:
    where = "entity_v2.get_entity_cards"
    try:
        return ent_services.get_entity_cards(
            entity_ulids=entity_ulids,
            include_contacts=include_contacts,
            include_addresses=include_addresses,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


__all__ = [
    "require_person_entity_ulid",
    "require_org_entity_ulid",
    "get_person_view",
    "get_org_view",
    "get_entity_labels",
    "get_entity_label",
    "get_entity_contact_summary",
    "get_entity_address_summary",
    "get_entity_cards",
]
