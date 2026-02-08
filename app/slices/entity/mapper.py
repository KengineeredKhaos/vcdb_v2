# app/slices/entity/mapper.py
from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from .models import Entity, EntityContact, EntityOrg, EntityPerson

"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.

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


class PersonView(TypedDict):
    entity_ulid: str
    kind: str  # "person"
    first_name: str
    last_name: str
    preferred_name: str | None
    email: str | None
    phone: str | None
    created_at_utc: datetime | None
    updated_at_utc: datetime | None


class OrgView(TypedDict):
    entity_ulid: str
    kind: str  # "org"
    legal_name: str
    dba_name: str | None
    ein: str | None
    email: str | None
    phone: str | None
    created_at_utc: datetime | None
    updated_at_utc: datetime | None


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
    "PersonView",
    "OrgView",
    "map_person_view",
    "map_org_view",
]
