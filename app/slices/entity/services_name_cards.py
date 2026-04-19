from __future__ import annotations

from collections.abc import Sequence

from flask import g
from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts.entity_v2 import EntityNameCardDTO
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

    loaded = _load_many([entity_ulid])
    dto = loaded.get(entity_ulid)
    if dto is None:
        raise LookupError("entity not found")

    cache[entity_ulid] = dto
    return dto


def get_entity_name_cards(
    entity_ulids: Sequence[str],
) -> list[EntityNameCardDTO]:
    cache = _req_cache()
    ordered = _ordered_unique_entity_ulids(entity_ulids)
    if not ordered:
        return []

    missing = [u for u in ordered if u not in cache]
    if missing:
        cache.update(_load_many(missing))

    return [cache[u] for u in ordered if u in cache]


def _ordered_unique_entity_ulids(entity_ulids: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for raw in entity_ulids:
        entity_ulid = str(raw or "").strip()
        if not entity_ulid or entity_ulid in seen:
            continue

        seen.add(entity_ulid)
        ordered.append(entity_ulid)

    return ordered


def _load_many(entity_ulids: Sequence[str]) -> dict[str, EntityNameCardDTO]:
    ordered = _ordered_unique_entity_ulids(entity_ulids)
    if not ordered:
        return {}

    entities = {
        row.ulid: row
        for row in db.session.execute(
            select(Entity).where(
                Entity.ulid.in_(ordered),
                Entity.archived_at.is_(None),
            )
        ).scalars()
    }

    person_rows = {
        row.entity_ulid: row
        for row in db.session.execute(
            select(EntityPerson).where(EntityPerson.entity_ulid.in_(ordered))
        ).scalars()
    }
    org_rows = {
        row.entity_ulid: row
        for row in db.session.execute(
            select(EntityOrg).where(EntityOrg.entity_ulid.in_(ordered))
        ).scalars()
    }

    out: dict[str, EntityNameCardDTO] = {}
    for entity_ulid in ordered:
        ent = entities.get(entity_ulid)
        if ent is None:
            continue
        out[entity_ulid] = _dto_for_entity(
            ent=ent,
            person=person_rows.get(entity_ulid),
            org=org_rows.get(entity_ulid),
        )
    return out


def _dto_for_entity(
    *,
    ent: Entity,
    person: EntityPerson | None,
    org: EntityOrg | None,
) -> EntityNameCardDTO:
    kind = _normalize_kind(ent.kind)

    if kind == "person":
        if person is None:
            raise LookupError("entity person facet missing")
        display, short = _fmt_person(person)
        return EntityNameCardDTO(ent.ulid, "person", display, short)

    if kind == "org":
        if org is None:
            raise LookupError("entity org facet missing")
        display, short = _fmt_org(org)
        return EntityNameCardDTO(ent.ulid, "org", display, short)

    if person is not None and org is None:
        display, short = _fmt_person(person)
        return EntityNameCardDTO(ent.ulid, "person", display, short)

    if org is not None and person is None:
        display, short = _fmt_org(org)
        return EntityNameCardDTO(ent.ulid, "org", display, short)

    raise LookupError("entity kind unsupported")


def _normalize_kind(raw: str | None) -> str | None:
    kind = (raw or "").strip().lower()
    if kind in ("org", "organization", "company", "nonprofit"):
        return "org"
    if kind in ("person", "human", "individual"):
        return "person"
    return None


def _fmt_person(person: EntityPerson) -> tuple[str, str | None]:
    first = (person.first_name or "").strip()
    preferred = (person.preferred_name or "").strip()
    lead = preferred or first
    last = (person.last_name or "").strip()

    if lead and last:
        return f"{lead} {last}", f"{last}, {lead[0]}."
    if last:
        return last, last
    if lead:
        return lead, lead
    return "Unnamed person", None


def _fmt_org(org: EntityOrg) -> tuple[str, str | None]:
    legal = (org.legal_name or "").strip()
    dba = (org.dba_name or "").strip()

    if dba:
        short = legal if legal and legal != dba else None
        return dba, short
    if legal:
        return legal, None
    return "Unnamed org", None
