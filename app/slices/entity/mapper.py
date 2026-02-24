# app/slices/entity/mapper.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from .models import Entity, EntityContact, EntityOrg, EntityPerson

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
    "WizardStepDTO",
    "WizardSummaryDTO",
    # Views (TypedDict)
    "PersonView",
    "OrgView",
    # View mappers
    "map_person_view",
    "map_org_view",
]
