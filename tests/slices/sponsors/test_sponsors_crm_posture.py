# tests/slices/sponsors/test_sponsors_crm_posture.py

from __future__ import annotations

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.mapper import sponsor_posture_to_dto
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_crm import (
    get_sponsor_posture,
    set_crm_factors,
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


def test_get_sponsor_posture_groups_factors_by_bucket(app):
    with app.app_context():
        sponsor = _create_sponsor("Posture Grouping Sponsor")

        out = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
                "style_reimbursement": {
                    "has": True,
                    "strength": "recurring",
                    "source": "observed",
                    "note": "Usually prefers receipts-backed asks.",
                },
                "friction_board_review": {
                    "has": False,
                    "strength": "observed",
                    "source": "operator",
                    "note": "Not common now, but worth remembering.",
                },
                "relationship_repeat_supporter": True,
            },
            actor_ulid=None,
            request_id="req-posture-grouping",
        )
        db.session.flush()

        assert out is not None

        posture = get_sponsor_posture(sponsor.entity_ulid)

        assert posture.sponsor_entity_ulid == sponsor.entity_ulid
        assert posture.active_factor_count == 3
        assert posture.note_hint_count == 2
        assert set(posture.factors_by_bucket.keys()) == {
            "mission",
            "style",
            "friction",
            "relationship",
        }

        mission = posture.factors_by_bucket["mission"][0]
        assert mission.key == "mission_housing"
        assert mission.label == "Housing"
        assert mission.active is True
        assert mission.strength == "observed"
        assert mission.source == "operator"
        assert mission.note is None

        style = posture.factors_by_bucket["style"][0]
        assert style.key == "style_reimbursement"
        assert style.label == "Reimbursement"
        assert style.active is True
        assert style.strength == "recurring"
        assert style.source == "observed"
        assert style.note == "Usually prefers receipts-backed asks."

        friction = posture.factors_by_bucket["friction"][0]
        assert friction.key == "friction_board_review"
        assert friction.active is False
        assert friction.note == ("Not common now, but worth remembering.")

        relationship = posture.factors_by_bucket["relationship"][0]
        assert relationship.key == "relationship_repeat_supporter"
        assert relationship.active is True


def test_get_sponsor_posture_returns_empty_view_when_no_snapshot(app):
    with app.app_context():
        sponsor = _create_sponsor("Empty Posture Sponsor")

        posture = get_sponsor_posture(sponsor.entity_ulid)

        assert posture.sponsor_entity_ulid == sponsor.entity_ulid
        assert posture.active_factor_count == 0
        assert posture.note_hint_count == 0
        assert posture.factors_by_bucket == {}


def test_get_sponsor_posture_preserves_taxonomy_order(app):
    with app.app_context():
        sponsor = _create_sponsor("Ordered Posture Sponsor")

        out = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
                "mission_local_veterans": True,
                "mission_basic_needs": True,
            },
            actor_ulid=None,
            request_id="req-posture-order",
        )
        db.session.flush()

        assert out is not None

        posture = get_sponsor_posture(sponsor.entity_ulid)

        mission_keys = [
            row.key for row in posture.factors_by_bucket["mission"]
        ]
        assert mission_keys == [
            "mission_local_veterans",
            "mission_housing",
            "mission_basic_needs",
        ]


def test_sponsor_posture_to_dto_shapes_output(app):
    with app.app_context():
        sponsor = _create_sponsor("Posture DTO Sponsor")

        out = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_prior_success": {
                    "has": True,
                    "strength": "strong_pattern",
                    "source": "observed",
                    "note": "Reliable repeat follow-through.",
                },
            },
            actor_ulid=None,
            request_id="req-posture-dto",
        )
        db.session.flush()

        assert out is not None

        posture = get_sponsor_posture(sponsor.entity_ulid)
        dto = sponsor_posture_to_dto(posture)

        assert dto["sponsor_entity_ulid"] == sponsor.entity_ulid
        assert dto["active_factor_count"] == 1
        assert dto["note_hint_count"] == 1
        assert set(dto["factors_by_bucket"].keys()) == {"relationship"}

        row = dto["factors_by_bucket"]["relationship"][0]
        assert row["key"] == "relationship_prior_success"
        assert row["label"] == "Prior success"
        assert row["active"] is True
        assert row["strength"] == "strong_pattern"
        assert row["source"] == "observed"
        assert row["note"] == "Reliable repeat follow-through."
