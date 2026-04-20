from __future__ import annotations

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.entity import services_wizard as wiz
from app.slices.entity.models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityPerson,
)


def _make_person_entity(
    *,
    intake_step: str | None = None,
    intake_request_id: str | None = None,
) -> Entity:
    ent = Entity(
        kind="person",
        intake_step=intake_step,
        intake_request_id=intake_request_id,
    )
    ent.person = EntityPerson(first_name="Test", last_name="Person")
    db.session.add(ent)
    db.session.commit()
    return ent


def test_blank_contact_advances_step_without_emit(app, monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        wiz.event_bus,
        "emit",
        lambda **payload: emitted.append(payload),
    )

    with app.app_context():
        rid = new_ulid()
        ent = _make_person_entity(intake_step=wiz.INTAKE_STEP_CONTACT)

        dto = wiz.wizard_contact(
            entity_ulid=ent.ulid,
            email=None,
            phone=None,
            request_id=rid,
            actor_ulid=None,
        )
        db.session.commit()
        db.session.refresh(ent)

        assert dto.entity_ulid == ent.ulid
        assert dto.created is False
        assert dto.changed_fields == ()
        assert dto.intake_step == wiz.INTAKE_STEP_ADDRESS
        assert dto.intake_request_id == rid
        assert dto.next_step == "entity.wizard_address"

        assert ent.intake_step == wiz.INTAKE_STEP_ADDRESS
        assert ent.intake_request_id == rid
        assert emitted == []


def test_unchanged_contact_advances_step_without_emit(app, monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        wiz.event_bus,
        "emit",
        lambda **payload: emitted.append(payload),
    )

    with app.app_context():
        rid = new_ulid()
        ent = _make_person_entity(
            intake_step=wiz.INTAKE_STEP_CONTACT,
            intake_request_id=rid,
        )
        db.session.add(
            EntityContact(
                entity_ulid=ent.ulid,
                is_primary=True,
                email="person@example.org",
                phone="5555551212",
            )
        )
        db.session.commit()

        dto = wiz.wizard_contact(
            entity_ulid=ent.ulid,
            email="person@example.org",
            phone="5555551212",
            request_id=new_ulid(),
            actor_ulid=None,
        )
        db.session.commit()
        db.session.refresh(ent)

        assert dto.changed_fields == ()
        assert dto.intake_step == wiz.INTAKE_STEP_ADDRESS
        assert dto.intake_request_id == rid
        assert ent.intake_step == wiz.INTAKE_STEP_ADDRESS
        assert ent.intake_request_id == rid
        assert emitted == []


def test_unchanged_address_advances_step_without_emit(app, monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        wiz.event_bus,
        "emit",
        lambda **payload: emitted.append(payload),
    )

    with app.app_context():
        rid = new_ulid()
        ent = _make_person_entity(
            intake_step=wiz.INTAKE_STEP_ADDRESS,
            intake_request_id=rid,
        )
        db.session.add(
            EntityAddress(
                entity_ulid=ent.ulid,
                is_physical=True,
                is_postal=False,
                address1="123 Main",
                address2=None,
                city="Somewhere",
                state="CA",
                postal_code="90210",
            )
        )
        db.session.commit()

        dto = wiz.wizard_address(
            entity_ulid=ent.ulid,
            is_physical=True,
            is_postal=False,
            address1="123 Main",
            address2=None,
            city="Somewhere",
            state="CA",
            postal_code="90210",
            request_id=new_ulid(),
            actor_ulid=None,
        )
        db.session.commit()
        db.session.refresh(ent)

        assert dto.changed_fields == ()
        assert dto.intake_step == wiz.INTAKE_STEP_ROLE
        assert dto.intake_request_id == rid
        assert ent.intake_step == wiz.INTAKE_STEP_ROLE
        assert ent.intake_request_id == rid
        assert emitted == []


def test_defer_address_advances_step_without_emit(app, monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        wiz.event_bus,
        "emit",
        lambda **payload: emitted.append(payload),
    )

    with app.app_context():
        rid = new_ulid()
        ent = _make_person_entity(
            intake_step=wiz.INTAKE_STEP_ADDRESS,
            intake_request_id=rid,
        )

        dto = wiz.wizard_defer_address(
            entity_ulid=ent.ulid,
            request_id=rid,
            actor_ulid=None,
        )
        db.session.commit()
        db.session.refresh(ent)

        assert dto.changed_fields == ()
        assert dto.intake_step == wiz.INTAKE_STEP_ROLE
        assert dto.intake_request_id == rid
        assert ent.intake_step == wiz.INTAKE_STEP_ROLE
        assert ent.intake_request_id == rid
        assert emitted == []
