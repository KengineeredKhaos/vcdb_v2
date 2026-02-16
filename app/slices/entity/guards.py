# app/slices/entity/guards.py
from __future__ import annotations

from app.extensions import db
from app.lib.ids import is_ulid_strict

from .models import Entity, EntityOrg, EntityPerson

__all__ = [
    "_clean_ulid",
    "require_entity",
    "require_wizard_entity",
    "require_entity_kind",
    "require_person_entity_ulid",
    "require_person_entity_ulid",
    "_validate_entity_shape",
]


def _clean_ulid(entity_ulid: str | None) -> str:
    val = (entity_ulid or "").strip()
    if not val:
        raise ValueError("entity_ulid is required")
    if not is_ulid_strict(val):
        raise ValueError("entity_ulid must be a valid ULID")
    return val


def require_entity(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> Entity:
    """
    Load + hard-check that an Entity exists.

    Returns the Entity row so callers can avoid repeating db.session.get()
    and can do further guards (shape checks, kind checks, etc).
    """
    ent_ulid = _clean_ulid(entity_ulid)

    ent = db.session.get(Entity, ent_ulid)
    if ent is None:
        raise LookupError("entity not found")

    if not allow_archived and getattr(ent, "archived_at", None):
        raise ValueError("entity is archived")

    return ent


def require_wizard_entity(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> Entity:
    ent = require_entity(entity_ulid, allow_archived=allow_archived)
    _validate_entity_shape(ent, allow_archived=allow_archived)
    return ent


def require_entity_kind(
    entity_ulid: str | None,
    *,
    kind: str,
    allow_archived: bool = False,
) -> None:
    ent = require_entity(entity_ulid, allow_archived=allow_archived)

    if ent.kind != kind:
        raise ValueError(f"entity kind must be '{kind}'")


def require_person_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> None:
    require_entity_kind(
        entity_ulid,
        kind="person",
        allow_archived=allow_archived,
    )


def require_org_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> None:
    require_entity_kind(
        entity_ulid,
        kind="org",
        allow_archived=allow_archived,
    )


def _validate_entity_shape(
    ent: Entity,
    *,
    allow_archived: bool = False,
) -> None:
    """
    Hard guard: entity must be structurally consistent with its kind.

    - kind must be 'person' or 'org'
    - if not allow_archived, archived entities are rejected
    - facet table must exist for the kind (PK=FK anchor = ent.ulid)
    - the *other* facet must not exist
    """
    if ent is None:
        raise LookupError("entity not found")

    if not is_ulid_strict(getattr(ent, "ulid", "")):
        raise ValueError("entity ulid must be a valid ULID")

    kind = (getattr(ent, "kind", "") or "").strip().lower()
    if kind not in {"person", "org"}:
        raise ValueError("entity kind must be 'person' or 'org'")

    if not allow_archived and getattr(ent, "archived_at", None):
        raise ValueError("entity is archived")

    # Facet shape checks (facet PK == entity ULID)
    if kind == "person":
        if db.session.get(EntityPerson, ent.ulid) is None:
            raise ValueError("entity person facet missing")
        if db.session.get(EntityOrg, ent.ulid) is not None:
            raise ValueError("org facet present for person entity")
        return

    # kind == "org"
    if db.session.get(EntityOrg, ent.ulid) is None:
        raise ValueError("entity org facet missing")
    if db.session.get(EntityPerson, ent.ulid) is not None:
        raise ValueError("person facet present for org entity")
