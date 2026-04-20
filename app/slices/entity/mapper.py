# app/slices/entity/mapper.py

from __future__ import annotations

from dataclasses import dataclass

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
    intake_step: str
    intake_request_id: str
    next_step: str


@dataclass(frozen=True, slots=True)
class OperatorCoreCreatedDTO:
    entity_ulid: str
    entity_kind: str
    display_name: str


@dataclass(frozen=True, slots=True)
class WizardStepDTO:
    entity_ulid: str
    intake_step: str
    intake_request_id: str
    created: bool
    changed_fields: tuple[str, ...]
    next_step: str


# -----------------
# Contact data setup
# -----------------


def _primary_contact_bits(
    entity_ulid: str,
    rows: list[EntityContact],
) -> tuple[str | None, str | None]:
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
        if len(emails) >= 1 and len(phones) >= 1:
            break

    primary_email = emails[0] if emails else None
    primary_phone = phones[0] if phones else None
    return primary_email, primary_phone


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

    role = ent.roles[0].role if ent.roles else None
    active_contacts = sorted(
        [c for c in (ent.contacts or []) if c.archived_at is None],
        key=lambda c: (
            1 if c.is_primary else 0,
            c.updated_at_utc or "",
            c.created_at_utc or "",
        ),
        reverse=True,
    )
    primary_email, primary_phone = _primary_contact_bits(
        ent.ulid,
        active_contacts,
    )

    return WizardSummaryDTO(
        entity_ulid=ent.ulid,
        kind=ent.kind,
        display_name=display.strip() or ent.ulid,
        role_code=role,
        email=primary_email,
        phone=primary_phone,
    )


__all__ = [
    # Wizard DTOs (dataclasses)
    "WizardEntityCreatedDTO",
    "WizardStepDTO",
    "WizardSummaryDTO",
]
