# tests/slices/sponsors/test_sponsors_crm_profile_note_hints.py

from __future__ import annotations

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.mapper import (
    sponsor_profile_note_hints_to_dto,
)
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services import set_profile_hints
from app.slices.sponsors.services_crm import (
    get_sponsor_profile_note_hints,
)


def _create_sponsor(name: str) -> Sponsor:
    entity = Entity(kind="org")
    db.session.add(entity)
    db.session.flush()

    db.session.add(
        EntityOrg(
            entity_ulid=entity.ulid,
            legal_name=name,
        )
    )

    sponsor = Sponsor(entity_ulid=entity.ulid)
    db.session.add(sponsor)
    db.session.flush()
    return sponsor


def test_get_sponsor_profile_note_hints_returns_empty_view_when_no_notes(
    app,
):
    with app.app_context():
        sponsor = _create_sponsor("Empty Profile Hints Sponsor")

        view = get_sponsor_profile_note_hints(sponsor.entity_ulid)

        assert view.sponsor_entity_ulid == sponsor.entity_ulid
        assert view.hint_count == 0
        assert view.hints == ()


def test_get_sponsor_profile_note_hints_returns_non_empty_notes(app):
    with app.app_context():
        sponsor = _create_sponsor("Profile Hints Sponsor")

        out = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_note": (
                    "Responsive when the ask is framed around housing."
                ),
                "recognition_note": ("Prefers simple public acknowledgment."),
            },
            actor_ulid=None,
            request_id="req-profile-hints-1",
        )
        db.session.flush()
        assert out is not None

        view = get_sponsor_profile_note_hints(sponsor.entity_ulid)

        assert view.sponsor_entity_ulid == sponsor.entity_ulid
        assert view.hint_count == 2

        assert view.hints[0].key == "relationship_note"
        assert view.hints[0].label == "Relationship note"
        assert view.hints[0].note == (
            "Responsive when the ask is framed around housing."
        )

        assert view.hints[1].key == "recognition_note"
        assert view.hints[1].label == "Recognition note"
        assert view.hints[1].note == ("Prefers simple public acknowledgment.")


def test_get_sponsor_profile_note_hints_ignores_blank_notes(app):
    with app.app_context():
        sponsor = _create_sponsor("Blank Profile Hints Sponsor")

        out = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_note": "   ",
                "recognition_note": "Recognition matters a bit.",
            },
            actor_ulid=None,
            request_id="req-profile-hints-2",
        )
        db.session.flush()
        assert out is not None

        view = get_sponsor_profile_note_hints(sponsor.entity_ulid)

        assert view.hint_count == 1
        assert len(view.hints) == 1
        assert view.hints[0].key == "recognition_note"
        assert view.hints[0].note == "Recognition matters a bit."


def test_sponsor_profile_note_hints_to_dto_shapes_output(app):
    with app.app_context():
        sponsor = _create_sponsor("Profile Hints DTO Sponsor")

        out = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_note": "Warm history with veteran-focused asks.",
            },
            actor_ulid=None,
            request_id="req-profile-hints-3",
        )
        db.session.flush()
        assert out is not None

        view = get_sponsor_profile_note_hints(sponsor.entity_ulid)
        dto = sponsor_profile_note_hints_to_dto(view)

        assert dto["sponsor_entity_ulid"] == sponsor.entity_ulid
        assert dto["hint_count"] == 1
        assert len(dto["hints"]) == 1

        row = dto["hints"][0]
        assert row["key"] == "relationship_note"
        assert row["label"] == "Relationship note"
        assert row["note"] == "Warm history with veteran-focused asks."
