from __future__ import annotations

import pytest

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.entity import services_wizard as wiz
from app.slices.entity.errors_wizard import WizardError
from app.slices.entity.models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityPerson,
    EntityRole,
)


def _make_person_entity(
    *,
    intake_step: str | None,
    intake_request_id: str | None = None,
) -> Entity:
    ent = Entity(
        kind="person",
        intake_step=intake_step,
        intake_request_id=intake_request_id,
    )
    ent.person = EntityPerson(first_name="State", last_name="Check")
    db.session.add(ent)
    db.session.commit()
    return ent


def test_wizard_next_step_maps_persisted_steps(app):
    with app.app_context():
        ent_contact = _make_person_entity(intake_step=wiz.INTAKE_STEP_CONTACT)
        ent_address = _make_person_entity(intake_step=wiz.INTAKE_STEP_ADDRESS)
        ent_role = _make_person_entity(intake_step=wiz.INTAKE_STEP_ROLE)
        ent_handoff = _make_person_entity(intake_step=wiz.INTAKE_STEP_HANDOFF)

        assert wiz.wizard_next_step(entity_ulid=ent_contact.ulid) == (
            "entity.wizard_contact"
        )
        assert wiz.wizard_next_step(entity_ulid=ent_address.ulid) == (
            "entity.wizard_address"
        )
        assert wiz.wizard_next_step(entity_ulid=ent_role.ulid) == (
            "entity.wizard_role_get"
        )
        assert wiz.wizard_next_step(entity_ulid=ent_handoff.ulid) == (
            "entity.wizard_next"
        )


def test_wizard_next_step_raises_when_intake_step_missing(app):
    with app.app_context():
        ent = _make_person_entity(intake_step=None)

        with pytest.raises(WizardError):
            wiz.wizard_next_step(entity_ulid=ent.ulid)


def test_wizard_next_step_raises_when_intake_step_invalid(app):
    with app.app_context():
        ent = _make_person_entity(intake_step="bananas")

        with pytest.raises(WizardError):
            wiz.wizard_next_step(entity_ulid=ent.ulid)


def test_wizard_next_step_does_not_fall_back_from_existing_rows(app):
    with app.app_context():
        ent = _make_person_entity(
            intake_step=None,
            intake_request_id=new_ulid(),
        )
        db.session.add(
            EntityContact(
                entity_ulid=ent.ulid,
                is_primary=True,
                email="state@example.org",
                phone=None,
            )
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
        db.session.add(EntityRole(entity_ulid=ent.ulid, role="civilian"))
        db.session.commit()

        with pytest.raises(WizardError):
            wiz.wizard_next_step(entity_ulid=ent.ulid)
