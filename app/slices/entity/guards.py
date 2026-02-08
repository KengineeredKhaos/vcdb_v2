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


def require_entity_kind(
    entity_ulid: str | None,
    *,
    kind: str,
    allow_archived: bool = False,
) -> None:
    ent_ulid = _clean_ulid(entity_ulid)

    ent = db.session.get(Entity, ent_ulid)
    if ent is None:
        raise LookupError("entity not found")

    if ent.kind != kind:
        raise ValueError(f"entity kind must be '{kind}'")

    if not allow_archived and getattr(ent, "archived_at", None):
        raise ValueError("entity is archived")


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
