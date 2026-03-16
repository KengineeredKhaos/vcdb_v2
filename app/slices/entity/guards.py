# app/slices/entity/guards.py
from __future__ import annotations

from app.extensions import db
from app.lib.ids import is_ulid_strict

from .models import Entity


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

    Load an Entity row or raise.

    Use this anywhere you would otherwise repeat:
        db.session.get(Entity, ...) + not-found checks.

    Note: This returns the ORM object. Do NOT log/emit PII fields.
    """
    ent_ulid = _clean_ulid(entity_ulid)

    ent = db.session.get(Entity, ent_ulid)
    if ent is None:
        raise LookupError("entity not found")

    if not allow_archived and getattr(ent, "archived_at", None):
        raise ValueError("entity is archived")

    return ent


def require_wizard_entity(entity_ulid: str | None) -> Entity:
    """Wizard-only: entity must exist and must not be archived."""

    return require_entity(entity_ulid, allow_archived=False)


def require_entity_kind(
    entity_ulid: str | None,
    *,
    kind: str,
    allow_archived: bool = False,
) -> Entity:
    ent = require_entity(entity_ulid, allow_archived=allow_archived)

    if ent.kind != kind:
        raise ValueError(f"entity kind must be '{kind}'")

    return ent


def require_person_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> Entity:
    return require_entity_kind(
        entity_ulid,
        kind="person",
        allow_archived=allow_archived,
    )


def require_org_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> Entity:
    return require_entity_kind(
        entity_ulid,
        kind="org",
        allow_archived=allow_archived,
    )


def _validate_entity_shape(ent: Entity) -> None:
    """Hard guard: ensure entity.kind matches its facet rows."""

    kind = (ent.kind or "").strip().lower()
    if kind == "person":
        if ent.person is None:
            raise ValueError("entity.person facet missing")
        if ent.org is not None:
            raise ValueError("entity has both person and org facets")
        return

    if kind == "org":
        if ent.org is None:
            raise ValueError("entity.org facet missing")
        if ent.person is not None:
            raise ValueError("entity has both org and person facets")
        return

    raise ValueError("unsupported entity kind")
