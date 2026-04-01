from __future__ import annotations

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg, EntityPerson
from app.slices.entity.services_name_cards import (
    get_entity_name_card,
    get_entity_name_cards,
)


def _make_person(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str | None = None,
    kind: str = "person",
    archived: bool = False,
) -> str:
    ent = Entity(
        kind=kind,
        archived_at=("2026-04-01T00:00:00Z" if archived else None),
    )
    db.session.add(ent)
    db.session.flush()

    db.session.add(
        EntityPerson(
            entity_ulid=ent.ulid,
            first_name=first_name,
            last_name=last_name,
            preferred_name=preferred_name,
        )
    )
    db.session.flush()
    return ent.ulid



def _make_org(
    *,
    legal_name: str,
    dba_name: str | None = None,
    kind: str = "org",
    archived: bool = False,
) -> str:
    ent = Entity(
        kind=kind,
        archived_at=("2026-04-01T00:00:00Z" if archived else None),
    )
    db.session.add(ent)
    db.session.flush()

    db.session.add(
        EntityOrg(
            entity_ulid=ent.ulid,
            legal_name=legal_name,
            dba_name=dba_name,
        )
    )
    db.session.flush()
    return ent.ulid



def test_get_entity_name_card_person_prefers_preferred_name(app):
    with app.app_context():
        entity_ulid = _make_person(
            first_name="Michael",
            last_name="Shaw",
            preferred_name="Mike",
        )

        card = get_entity_name_card(entity_ulid)

        assert card.entity_ulid == entity_ulid
        assert card.kind == "person"
        assert card.display_name == "Mike Shaw"
        assert card.short_label == "Shaw, M."



def test_get_entity_name_card_org_prefers_dba_and_uses_legal_as_short(
    app,
):
    with app.app_context():
        entity_ulid = _make_org(
            legal_name="Veterans Community Development Board",
            dba_name="Vet Connect",
        )

        card = get_entity_name_card(entity_ulid)

        assert card.entity_ulid == entity_ulid
        assert card.kind == "org"
        assert card.display_name == "Vet Connect"
        assert card.short_label == "Veterans Community Development Board"



def test_get_entity_name_cards_preserves_first_seen_order_and_dedupes(app):
    with app.app_context():
        first = _make_person(
            first_name="Michael",
            last_name="Shaw",
            preferred_name="Mike",
        )
        second = _make_org(
            legal_name="Veterans Community Development Board",
            dba_name="Vet Connect",
        )
        archived = _make_person(
            first_name="Archived",
            last_name="Person",
            archived=True,
        )
        missing = "01MISSINGENTITYULID00000000"

        cards = get_entity_name_cards(
            [second, first, second, "", missing, archived, first]
        )

        assert [card.entity_ulid for card in cards] == [second, first]
        assert [card.display_name for card in cards] == [
            "Vet Connect",
            "Mike Shaw",
        ]



def test_get_entity_name_card_raises_for_archived_entity_by_default(app):
    with app.app_context():
        entity_ulid = _make_org(
            legal_name="Archived Org",
            dba_name="ArchiveCo",
            archived=True,
        )

        try:
            get_entity_name_card(entity_ulid)
        except LookupError as exc:
            assert "not found" in str(exc)
        else:
            raise AssertionError("expected LookupError for archived entity")
