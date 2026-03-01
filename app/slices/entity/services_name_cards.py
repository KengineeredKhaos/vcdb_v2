from __future__ import annotations

from collections.abc import Sequence

from flask import g

from app.extensions import db
from app.slices.entity.mapper import EntityNameCardDTO
from app.slices.entity.models import Entity, EntityOrg, EntityPerson


def _req_cache() -> dict[str, EntityNameCardDTO]:
    cache = getattr(g, "_entity_name_card_cache", None)
    if cache is None:
        cache = {}
        g._entity_name_card_cache = cache
    return cache


def get_entity_name_card(entity_ulid: str) -> EntityNameCardDTO:
    cache = _req_cache()
    hit = cache.get(entity_ulid)
    if hit is not None:
        return hit

    dto = _load_one(entity_ulid)
    cache[entity_ulid] = dto
    return dto


def get_entity_name_cards(
    entity_ulids: Sequence[str],
) -> list[EntityNameCardDTO]:
    cache = _req_cache()
    out: list[EntityNameCardDTO] = []

    for u in entity_ulids:
        if not u:
            continue
        hit = cache.get(u)
        if hit is None:
            try:
                hit = _load_one(u)
                cache[u] = hit
            except LookupError:
                continue
        out.append(hit)

    # preserve caller order, omit missing
    idx = {d.entity_ulid: d for d in out}
    return [idx[u] for u in entity_ulids if u in idx]


def _load_one(entity_ulid: str) -> EntityNameCardDTO:
    ent = db.session.get(Entity, entity_ulid)
    if ent is None:
        raise LookupError("entity not found")

    kind = _normalize_kind(ent.kind)

    # If kind is unknown/odd, infer from facet existence.
    org = db.session.get(EntityOrg, entity_ulid)
    person = db.session.get(EntityPerson, entity_ulid)

    if kind == "org" or (kind is None and org is not None):
        if org is None:
            raise LookupError("entity org facet missing")
        display = (org.legal_name or "").strip() or "Unnamed org"
        short = (org.dba_name or "").strip() or None
        return EntityNameCardDTO(entity_ulid, "org", display, short)

    if kind == "person" or (kind is None and person is not None):
        if person is None:
            raise LookupError("entity person facet missing")
        display, short = _fmt_person(person)
        return EntityNameCardDTO(entity_ulid, "person", display, short)

    raise LookupError("entity kind unsupported")


def _normalize_kind(raw: str | None) -> str | None:
    k = (raw or "").strip().lower()
    if k in ("org", "organization", "company", "nonprofit"):
        return "org"
    if k in ("person", "human", "individual"):
        return "person"
    return None


def _fmt_person(person: EntityPerson) -> tuple[str, str | None]:
    first = (person.preferred_name or person.first_name or "").strip()
    last = (person.last_name or "").strip()

    if first and last:
        return f"{last}, {first}", f"{last}, {first[0]}."
    if last:
        return last, last
    if first:
        return first, first
    return "Unnamed person", None
