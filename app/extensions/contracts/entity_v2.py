# app/extensions/contracts/entity_v2.py

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from app.extensions.errors import ContractError
from app.lib.ids import is_ulid  # or your canonical ULID validator

if TYPE_CHECKING:
    from app.slices.entity.models import (
        Entity,
        EntityAddress,
        EntityContact,
        EntityOrg,
        EntityPerson,
    )

# -----------------
# Contract Error
# Handlers
# -----------------


def _validated_ulids(
    entity_ulids: Sequence[str],
    *,
    where: str,
) -> list[str]:
    vals = [str(u).strip() for u in (entity_ulids or []) if str(u).strip()]
    bad = [u for u in vals if not is_ulid(u)]
    if bad:
        raise ContractError(
            code="bad_argument",
            where=where,
            message="one or more invalid entity_ulids",
            http_status=400,
        )
    return vals


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc
    msg = str(exc) or exc.__class__.__name__
    if isinstance(exc, ValueError) and msg == "entity is archived":
        return ContractError(
            code="not_found",
            where=where,
            message=msg,
            http_status=404,
        )
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
        from app.slices.entity import guards as ent_guards

        ent = ent_guards.require_person_entity_ulid(
            entity_ulid,
            allow_archived=allow_archived,
        )
        return ent.ulid
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
        from app.slices.entity import guards as ent_guards

        ent = ent_guards.require_org_entity_ulid(
            entity_ulid,
            allow_archived=allow_archived,
        )
        return ent.ulid
    except Exception as exc:
        raise _as_contract_error(err_where, exc) from exc


# -----------------
# DTOs + helper mappers
# Contract-owned
# cross-slice shapes live here.
# -----------------


@dataclass(frozen=True, slots=True)
class EntityLabelDTO:
    """Minimal cross-slice label for an entity."""

    entity_ulid: str
    kind: str
    display_name: str
    first_name: str | None
    last_name: str | None
    preferred_name: str | None
    legal_name: str | None
    dba_name: str | None


@dataclass(frozen=True, slots=True)
class EntityContactSummaryDTO:
    entity_ulid: str
    primary_email: str | None
    primary_phone: str | None
    secondary_email: str | None
    secondary_phone: str | None


@dataclass(frozen=True, slots=True)
class EntityAddressDTO:
    address1: str
    address2: str | None
    city: str
    state: str
    postal_code: str


@dataclass(frozen=True, slots=True)
class EntityAddressSummaryDTO:
    entity_ulid: str
    physical: EntityAddressDTO | None
    postal: EntityAddressDTO | None


@dataclass(frozen=True, slots=True)
class EntityCardDTO:
    entity_ulid: str
    label: EntityLabelDTO
    contacts: EntityContactSummaryDTO | None
    addresses: EntityAddressSummaryDTO | None


EntityKind = Literal["person", "org"]


@dataclass(frozen=True, slots=True)
class EntityNameCardDTO:
    entity_ulid: str
    kind: EntityKind
    display_name: str
    short_label: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorCoreCreatedDTO:
    entity_ulid: str
    entity_kind: str
    display_name: str


class PersonView(TypedDict):
    entity_ulid: str
    first_name: str
    last_name: str
    preferred_name: str | None
    email: str | None
    phone: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


class OrgView(TypedDict):
    entity_ulid: str
    legal_name: str
    dba_name: str | None
    ein: str | None
    email: str | None
    phone: str | None
    created_at_utc: str | None
    updated_at_utc: str | None


def entity_label_to_dict(label: EntityLabelDTO) -> dict[str, Any]:
    return asdict(label)


def entity_card_to_dict(card: EntityCardDTO) -> dict[str, Any]:
    return asdict(card)


def to_contact_summary(
    entity_ulid: str,
    rows: list[EntityContact],
) -> EntityContactSummaryDTO:
    emails: list[str] = []
    phones: list[str] = []

    for row in rows:
        if row.email:
            email = row.email.strip()
            if email:
                emails.append(email)
        if row.phone:
            phone = row.phone.strip()
            if phone:
                phones.append(phone)
        if len(emails) >= 2 and len(phones) >= 2:
            break

    return EntityContactSummaryDTO(
        entity_ulid=entity_ulid,
        primary_email=emails[0] if len(emails) > 0 else None,
        secondary_email=emails[1] if len(emails) > 1 else None,
        primary_phone=phones[0] if len(phones) > 0 else None,
        secondary_phone=phones[1] if len(phones) > 1 else None,
    )


def _to_addr(row: EntityAddress) -> EntityAddressDTO:
    return EntityAddressDTO(
        address1=row.address1,
        address2=row.address2,
        city=row.city,
        state=row.state,
        postal_code=row.postal_code,
    )


def to_address_summary(
    entity_ulid: str,
    rows: list[EntityAddress],
) -> EntityAddressSummaryDTO:
    physical: EntityAddressDTO | None = None
    postal: EntityAddressDTO | None = None

    for row in rows:
        if physical is None and bool(row.is_physical):
            physical = _to_addr(row)
        if postal is None and bool(row.is_postal):
            postal = _to_addr(row)
        if physical is not None and postal is not None:
            break

    return EntityAddressSummaryDTO(
        entity_ulid=entity_ulid,
        physical=physical,
        postal=postal,
    )


def _active_contact_summary(
    ent: Entity | None,
) -> EntityContactSummaryDTO | None:
    if not ent or not ent.contacts:
        return None

    rows = sorted(
        [row for row in ent.contacts if row.archived_at is None],
        key=lambda row: (
            1 if row.is_primary else 0,
            row.updated_at_utc or "",
            row.created_at_utc or "",
        ),
        reverse=True,
    )
    return to_contact_summary(ent.ulid, rows)


def map_person_view(person: EntityPerson) -> PersonView:
    ent = person.entity
    summary = _active_contact_summary(ent)
    return {
        "entity_ulid": ent.ulid if ent else person.entity_ulid,
        "first_name": person.first_name,
        "last_name": person.last_name,
        "preferred_name": person.preferred_name,
        "email": summary.primary_email if summary else None,
        "phone": summary.primary_phone if summary else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


def map_org_view(org: EntityOrg) -> OrgView:
    ent = org.entity
    summary = _active_contact_summary(ent)
    return {
        "entity_ulid": ent.ulid if ent else org.entity_ulid,
        "legal_name": org.legal_name,
        "dba_name": org.dba_name,
        "ein": org.ein,
        "email": summary.primary_email if summary else None,
        "phone": summary.primary_phone if summary else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


# -----------------
# Name Cards
# (slice-agnostic)
# -----------------

"""
Semantics:

display_name: “safe UI name” (no DOB/last4/address/phone/email).
person: e.g. "Shaw, Mike" or "Mike Shaw"
org: trade/doing-business-as if present, else legal name
short_label (optional): compact label for tight UIs
person: "Shaw, M."
org: "ACME" / truncated trade name
No other fields. No “reason”, “notes”, “identifiers”, etc.

How other slices should use it:

For one-off places (headers, detail pages): get_entity_name_card()
For lists/reports: get_entity_name_cards([...])
Slices store only entity_ulid in their tables; they fetch display
cards at render/export time via the contract.
"""


def get_entity_name_card(entity_ulid: str) -> EntityNameCardDTO:
    """
    Return a minimal, PII-minimal display card for the given entity ULID.

    Failure behavior:
      - bad_argument (400): invalid ULID
      - not_found (404): ULID not present
      - unavailable (503): DB/session unavailable
      - internal_error (500): unexpected
    """
    where = "entity_v2.get_entity_name_card"
    if not is_ulid(entity_ulid):
        raise ContractError(
            code="bad_argument",
            where=where,
            message="invalid entity_ulid",
            http_status=400,
        )

    try:
        from app.slices.entity.services_name_cards import (
            get_entity_name_card as _get_entity_name_card,
        )

        return _get_entity_name_card(entity_ulid)
    except LookupError as err:
        raise ContractError(
            code="not_found",
            where=where,
            message=str(err) or "entity not found",
            http_status=404,
        ) from err
    except ConnectionError as err:
        raise ContractError(
            code="unavailable",
            where=where,
            message="entity data unavailable",
            http_status=503,
        ) from err
    except Exception as err:
        raise ContractError(
            code="internal_error",
            where=where,
            message="unexpected error",
            http_status=500,
        ) from err


def get_entity_name_cards(
    entity_ulids: Sequence[str],
) -> list[EntityNameCardDTO]:
    """
    Batch variant to avoid N+1 loops in lists/reports.

    Notes:
      - Invalid ULIDs => bad_argument (400)
      - Missing ULIDs are omitted (or choose to return placeholders)
        to keep callers simple; if you prefer strictness, flip to 404.
    """
    where = "entity_v2.get_entity_name_cards"
    bad = [u for u in entity_ulids if not is_ulid(u)]
    if bad:
        raise ContractError(
            code="bad_argument",
            where=where,
            message="one or more invalid entity_ulids",
            http_status=400,
        )

    try:
        from app.slices.entity.services_name_cards import (
            get_entity_name_cards as _get_entity_name_cards,
        )

        return _get_entity_name_cards(entity_ulids)
    except ConnectionError as err:
        raise ContractError(
            code="unavailable",
            where=where,
            message="entity data unavailable",
            http_status=503,
        ) from err
    except Exception as err:
        raise ContractError(
            code="internal_error",
            where=where,
            message="unexpected error",
            http_status=500,
        ) from err


# -----------------
# Entity Data
# Edit/Update
# -----------------


def create_operator_core(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str,
    request_id: str,
    actor_ulid: str | None,
) -> OperatorCoreCreatedDTO:
    where = "entity_v2.create_operator_core"
    try:
        from app.slices.entity import services as ent_services

        return ent_services.create_operator_core(
            first_name=first_name,
            last_name=last_name,
            preferred_name=preferred_name,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Summary Views
# -----------------


def get_person_view(entity_ulid: str) -> PersonView:
    where = "entity_v2.get_person_view"
    try:
        from app.slices.entity import guards as ent_guards
        from app.slices.entity import services as ent_services

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
        from app.slices.entity import guards as ent_guards
        from app.slices.entity import services as ent_services

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
        from app.slices.entity import services as ent_services

        _validated_ulids(entity_ulids, where=where)
        return ent_services.get_entity_labels(entity_ulids=entity_ulids)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_entity_label(entity_ulid: str) -> EntityLabelDTO:
    where = "entity_v2.get_entity_label"
    try:
        from app.slices.entity import services as ent_services

        if not is_ulid(entity_ulid):
            raise ContractError(
                code="bad_argument",
                where=where,
                message="invalid entity_ulid",
                http_status=400,
            )
        d = ent_services.get_entity_labels(entity_ulids=[entity_ulid])
        v = d.get(entity_ulid)
        if v is None or v.kind == "unknown":
            raise LookupError("entity not found")
        return v
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_entity_contact_summary(
    *, entity_ulids: list[str]
) -> dict[str, EntityContactSummaryDTO]:
    where = "entity_v2.get_entity_contact_summary"
    try:
        from app.slices.entity import services as ent_services

        _validated_ulids(entity_ulids, where=where)
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
        from app.slices.entity import services as ent_services

        _validated_ulids(entity_ulids, where=where)
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
        from app.slices.entity import services as ent_services

        _validated_ulids(entity_ulids, where=where)
        return ent_services.get_entity_cards(
            entity_ulids=entity_ulids,
            include_contacts=include_contacts,
            include_addresses=include_addresses,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


__all__ = [
    "EntityLabelDTO",
    "EntityContactSummaryDTO",
    "EntityAddressDTO",
    "EntityAddressSummaryDTO",
    "EntityCardDTO",
    "EntityNameCardDTO",
    "OperatorCoreCreatedDTO",
    "PersonView",
    "OrgView",
    "entity_label_to_dict",
    "entity_card_to_dict",
    "to_contact_summary",
    "to_address_summary",
    "map_person_view",
    "map_org_view",
    "create_operator_core",
    "require_person_entity_ulid",
    "require_org_entity_ulid",
    "get_entity_name_card",
    "get_entity_name_cards",
    "get_person_view",
    "get_org_view",
    "get_entity_labels",
    "get_entity_label",
    "get_entity_contact_summary",
    "get_entity_address_summary",
    "get_entity_cards",
]
