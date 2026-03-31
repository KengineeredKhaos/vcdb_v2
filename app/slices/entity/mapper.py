# app/slices/entity/mapper.py

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, TypedDict

from .models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityOrg,
    EntityPerson,
)

"""
Slice-local projection layer.

Naming Conventions:
    *DTO suffix for dataclasses crossing boundaries
    (WizardCreatedDTO, EntityCardDTO).

    *View suffix for TypedDict view models
    (PersonView, OrgView).

DTOs should be “what the caller needs”, not “everything we happen to have”.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.

@dataclass(frozen=True, slots=True) DTOS are for transfering slice data
used in contracts for data that crosses slice boundries. They are:

    Immutable (frozen=True) → contract results are facts, not mutable objects.
    Dot access (dto.field) → minimizes cognitive overhead.
    Slots (slots=True) → prevents accidental attribute injection
    and reduces memory overhead.
    Clear, typed fields → easier testing and refactoring.

TypedDicts are for READ-ONLY JSON transactions.
Use TypedDict only for “baggy” payloads where:
    the shape is inherently dict-like
    the schema is external (policy JSON) or intentionally flexible
    the payload is rows/buckets/blobs
    (reporting, aggregation, CSV-ish outputs)
    if you want a view model that is naturally serialized as JSON
    without transformation.


Mapped JSON payload: (for reference only)
{
  "kind": "person",
  "role": "customer",
  "person": { "first_name": "...", "last_name": "...", "preferred_name": null,
              "dob": null, "last_4": null, "branch": null, "era": null },
  "contact": { "email": "...", "phone": "...", "is_primary": true },
  "address": { "is_physical": true, "is_postal": false, "address": "...",
               "address2": "...", "city": "...", "state": "...",
               "postal_code": "..." },
  "entity_ulid": "01..."   // optional
}

"""
# -----------------
# Entity_v2 DTO's
# -----------------


@dataclass(frozen=True, slots=True)
class EntityLabelDTO:
    """
    Minimal, UI-oriented label for cross-slice display.
    PII is intentionally limited to names (no email/phone/address).
    """

    entity_ulid: str
    kind: str  # "person" | "org" | "unknown"
    display_name: str
    # People (optional)
    first_name: str | None
    last_name: str | None
    preferred_name: str | None
    # Orgs (optional)
    legal_name: str | None
    dba_name: str | None


# -----------------
# services_wizard
# DTO's
# -----------------


@dataclass(frozen=True, slots=True)
class WizardSummaryDTO:
    entity_ulid: str
    kind: str
    display_name: str
    role_code: str | None
    email: str | None
    phone: str | None


@dataclass(frozen=True, slots=True)
class WizardEntityCreatedDTO:
    entity_ulid: str
    entity_kind: str
    display_name: str
    next_step: str


@dataclass(frozen=True, slots=True)
class OperatorCoreCreatedDTO:
    entity_ulid: str
    entity_kind: str
    display_name: str


@dataclass(frozen=True, slots=True)
class WizardStepDTO:
    entity_ulid: str
    created: bool
    changed_fields: tuple[str, ...]
    next_step: str


# -----------------
# TypedDict
# Blobs/Views
# -----------------


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


# -----------------
# Wizard Summary
# -----------------


def to_wizard_summary(ent: Entity) -> WizardSummaryDTO:
    p = ent.person
    o = ent.org

    if p is not None:
        display = " ".join(x for x in [p.first_name, p.last_name] if x)
    else:
        display = (o.legal_name or "") if o is not None else ent.ulid

    role = ent.roles[0].role_code if ent.roles else None
    c = ent.contacts[0] if ent.contacts else None

    return WizardSummaryDTO(
        entity_ulid=ent.ulid,
        kind=ent.kind,
        display_name=display.strip() or ent.ulid,
        role_code=role,
        email=(c.email if c else None),
        phone=(c.phone if c else None),
    )


# -----------------
# Entity_v2 DTO's (Rolodex)
# -----------------


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
    """
    Rolodex "card": label always; contacts/addresses are opt-in.
    """

    entity_ulid: str
    label: EntityLabelDTO
    contacts: EntityContactSummaryDTO | None
    addresses: EntityAddressSummaryDTO | None


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
"""

EntityKind = Literal["person", "org"]


@dataclass(frozen=True, slots=True)
class EntityNameCardDTO:
    entity_ulid: str
    kind: EntityKind
    display_name: str
    short_label: str | None = None


# -----------------
# Rolodex View-builder
# functions
# -----------------


def entity_label_to_dict(label: EntityLabelDTO) -> dict[str, Any]:
    # asdict() recursively converts nested dataclasses to dicts/lists
    return asdict(label)


def entity_card_to_dict(card: EntityCardDTO) -> dict[str, Any]:
    # asdict() recursively converts nested dataclasses to dicts/lists
    return asdict(card)


def to_contact_summary(
    entity_ulid: str,
    rows: list[EntityContact],
) -> EntityContactSummaryDTO:
    # rows are expected to be pre-sorted best-first
    emails: list[str] = []
    phones: list[str] = []

    for c in rows:
        if c.email:
            e = c.email.strip()
            if e:
                emails.append(e)
        if c.phone:
            p = c.phone.strip()
            if p:
                phones.append(p)
        if len(emails) >= 2 and len(phones) >= 2:
            break

    return EntityContactSummaryDTO(
        entity_ulid=entity_ulid,
        primary_email=emails[0] if len(emails) > 0 else None,
        secondary_email=emails[1] if len(emails) > 1 else None,
        primary_phone=phones[0] if len(phones) > 0 else None,
        secondary_phone=phones[1] if len(phones) > 1 else None,
    )


def _to_addr(a: EntityAddress) -> EntityAddressDTO:
    return EntityAddressDTO(
        address1=a.address1,
        address2=a.address2,
        city=a.city,
        state=a.state,
        postal_code=a.postal_code,
    )


def to_address_summary(
    entity_ulid: str,
    rows: list[EntityAddress],
) -> EntityAddressSummaryDTO:
    # rows are expected to be pre-sorted newest-first
    physical: EntityAddressDTO | None = None
    postal: EntityAddressDTO | None = None

    for a in rows:
        if physical is None and bool(a.is_physical):
            physical = _to_addr(a)
        if postal is None and bool(a.is_postal):
            postal = _to_addr(a)
        if physical is not None and postal is not None:
            break

    return EntityAddressSummaryDTO(
        entity_ulid=entity_ulid,
        physical=physical,
        postal=postal,
    )


# -----------------
# other functions
# -----------------


def _pick_primary_contact(ent: Entity | None) -> EntityContact | None:
    if not ent or not ent.contacts:
        return None
    for c in ent.contacts:
        if c.is_primary:
            return c
    return None


def map_person_view(p: EntityPerson) -> PersonView:
    ent = p.entity
    primary = _pick_primary_contact(ent)
    return {
        "entity_ulid": ent.ulid if ent else p.entity_ulid,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "preferred_name": p.preferred_name,
        "email": primary.email if primary else None,
        "phone": primary.phone if primary else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


def map_org_view(o: EntityOrg) -> OrgView:
    ent = o.entity
    primary = _pick_primary_contact(ent)
    return {
        "entity_ulid": ent.ulid if ent else o.entity_ulid,
        "legal_name": o.legal_name,
        "dba_name": o.dba_name,
        "ein": o.ein,
        "email": primary.email if primary else None,
        "phone": primary.phone if primary else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


__all__ = [
    # Entity_v2 DTOs
    "EntityLabelDTO",
    # Wizard DTOs (dataclasses)
    "WizardEntityCreatedDTO",
    "OperatorCoreCreatedDTO",
    "WizardStepDTO",
    "WizardSummaryDTO",
    # Rolodex (TypedDict)
    "EntityCardDTO",
    "EntityAddressDTO",
    "EntityAddressSummaryDTO",
    "EntityContactSummaryDTO",
    # Rolodex Builders
    "to_contact_summary",
    "_to_addr",
    "to_address_summary",
    # Views (TypedDict)
    "PersonView",
    "OrgView",
    # View mappers
    "map_person_view",
    "map_org_view",
]
