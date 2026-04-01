from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.extensions import db
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError
from app.slices.entity.models import Entity
from app.slices.entity import services as ent_services


REQ = "01REQREQREQREQREQREQREQREQ"
ACTOR = "01ACTORACTORACTORACTORACT"


def _make_person(
    *, first: str = "Michael", last: str = "Shaw", pref: str = "Mike"
) -> str:
    created = entity_v2.create_operator_core(
        first_name=first,
        last_name=last,
        preferred_name=pref,
        request_id=REQ,
        actor_ulid=ACTOR,
    )
    return created.entity_ulid


def _make_org(
    *, legal_name: str = "Acme Incorporated", dba_name: str | None = "Acme"
) -> str:
    return ent_services.ensure_org(
        legal_name=legal_name,
        dba_name=dba_name,
        request_id=REQ,
        actor_ulid=ACTOR,
    )


def test_require_person_entity_ulid_returns_ulid_string(app):
    with app.app_context():
        person_ulid = _make_person()

        out = entity_v2.require_person_entity_ulid(person_ulid)

        assert out == person_ulid
        assert isinstance(out, str)


def test_require_org_entity_ulid_returns_ulid_string(app):
    with app.app_context():
        org_ulid = _make_org()

        out = entity_v2.require_org_entity_ulid(org_ulid)

        assert out == org_ulid
        assert isinstance(out, str)


def test_require_person_entity_ulid_rejects_wrong_kind(app):
    with app.app_context():
        org_ulid = _make_org()

        with pytest.raises(ContractError) as exc:
            entity_v2.require_person_entity_ulid(org_ulid)

        assert exc.value.code == "bad_argument"
        assert exc.value.http_status == 400


def test_get_entity_label_missing_is_not_found(app):
    with app.app_context():
        missing = "01AAAAAAAAAAAAAAAAAAAAAAAA"

        with pytest.raises(ContractError) as exc:
            entity_v2.get_entity_label(missing)

        assert exc.value.code == "not_found"
        assert exc.value.http_status == 404


def test_get_entity_name_card_invalid_ulid_is_bad_argument(app):
    with app.app_context():
        with pytest.raises(ContractError) as exc:
            entity_v2.get_entity_name_card("not-a-ulid")

        assert exc.value.code == "bad_argument"
        assert exc.value.http_status == 400


def test_get_entity_name_cards_invalid_batch_is_bad_argument(app):
    with app.app_context():
        person_ulid = _make_person()

        with pytest.raises(ContractError) as exc:
            entity_v2.get_entity_name_cards([person_ulid, "bogus"])

        assert exc.value.code == "bad_argument"
        assert exc.value.http_status == 400


def test_get_person_view_returns_contact_fields(app):
    with app.app_context():
        person_ulid = _make_person()
        ent_services.edit_contact(
            entity_ulid=person_ulid,
            email="mike@example.org",
            phone="4085551212",
            request_id=REQ,
            actor_ulid=ACTOR,
        )
        db.session.commit()

        view = entity_v2.get_person_view(person_ulid)

        assert view["entity_ulid"] == person_ulid
        assert view["preferred_name"] == "Mike"
        assert view["email"] == "mike@example.org"
        assert view["phone"] == "4085551212"


def test_get_org_view_returns_contact_fields(app):
    with app.app_context():
        org_ulid = _make_org()
        ent_services.edit_contact(
            entity_ulid=org_ulid,
            email="hello@acme.org",
            phone="4085550000",
            request_id=REQ,
            actor_ulid=ACTOR,
        )
        db.session.commit()

        view = entity_v2.get_org_view(org_ulid)

        assert view["entity_ulid"] == org_ulid
        assert view["legal_name"] == "Acme Incorporated"
        assert view["dba_name"] == "Acme"
        assert view["email"] == "hello@acme.org"
        assert view["phone"] == "4085550000"


def test_get_entity_cards_includes_contact_and_address_summaries(app):
    with app.app_context():
        person_ulid = _make_person()
        ent_services.edit_contact(
            entity_ulid=person_ulid,
            email="mike@example.org",
            phone="4085551212",
            request_id=REQ,
            actor_ulid=ACTOR,
        )
        ent_services.upsert_address(
            entity_ulid=person_ulid,
            address1="123 Main St",
            address2=None,
            city="San Jose",
            state="CA",
            postal_code="95112",
            is_physical=True,
            is_postal=False,
            request_id=REQ,
            actor_ulid=ACTOR,
        )
        db.session.commit()

        cards = entity_v2.get_entity_cards(
            entity_ulids=[person_ulid],
            include_contacts=True,
            include_addresses=True,
        )
        card = cards[person_ulid]

        assert card.label.entity_ulid == person_ulid
        assert card.contacts is not None
        assert card.contacts.primary_email == "mike@example.org"
        assert card.addresses is not None
        assert card.addresses.physical is not None
        assert card.addresses.physical.city == "San Jose"
        assert card.addresses.physical.state == "CA"
        assert card.addresses.physical.postal_code == "95112"


def test_archived_entity_reads_default_to_not_found(app):
    with app.app_context():
        person_ulid = _make_person()
        ent = db.session.get(Entity, person_ulid)
        assert ent is not None
        ent.archived_at = datetime.now(UTC)
        db.session.commit()

        with pytest.raises(ContractError) as exc:
            entity_v2.require_person_entity_ulid(person_ulid)

        assert exc.value.code == "not_found"
        assert exc.value.http_status == 404
