
from __future__ import annotations

from app.extensions import db
from app.slices.entity import services_wizard as wiz
from app.slices.entity.models import EntityAddress, EntityContact, EntityRole

REQ = "01AAAAAAAAAAAAAAAAAAAAAAAAAA"
ACTOR = None


def test_wizard_contact_allows_blank_without_creating_contact_row(app):
    with app.app_context():
        created = wiz.wizard_create_person_core(
            first_name="Mike",
            last_name="Shaw",
            preferred_name=None,
            dob=None,
            last_4=None,
            request_id=REQ,
            actor_ulid=ACTOR,
        )

        step = wiz.wizard_contact(
            entity_ulid=created.entity_ulid,
            email=None,
            phone=None,
            request_id=REQ,
            actor_ulid=ACTOR,
        )

        db.session.flush()

        assert step.entity_ulid == created.entity_ulid
        assert step.changed_fields == ()
        assert step.next_step == "entity.wizard_address"

        rows = (
            db.session.query(EntityContact)
            .filter(EntityContact.entity_ulid == created.entity_ulid)
            .all()
        )
        assert rows == []


def test_wizard_minimum_valid_creation_is_core_plus_role(app):
    with app.app_context():
        created = wiz.wizard_create_person_core(
            first_name="Jane",
            last_name="Doe",
            preferred_name=None,
            dob=None,
            last_4=None,
            request_id=REQ,
            actor_ulid=ACTOR,
        )

        # Honest gap: no contact at intake.
        wiz.wizard_contact(
            entity_ulid=created.entity_ulid,
            email=None,
            phone=None,
            request_id=REQ,
            actor_ulid=ACTOR,
        )

        # Honest gap: no address row at intake.
        # Wizard route handles "skip for now"; service fallback should still
        # consider core + role to be minimally complete.
        step = wiz.wizard_set_single_role(
            entity_ulid=created.entity_ulid,
            role="customer",
            request_id=REQ,
            actor_ulid=ACTOR,
        )

        db.session.flush()

        assert step.next_step == "entity.wizard_next"

        roles = (
            db.session.query(EntityRole)
            .filter(
                EntityRole.entity_ulid == created.entity_ulid,
                EntityRole.archived_at.is_(None),
            )
            .all()
        )
        assert len(roles) == 1
        assert roles[0].role == "customer"

        contacts = (
            db.session.query(EntityContact)
            .filter(EntityContact.entity_ulid == created.entity_ulid)
            .all()
        )
        assert contacts == []

        addresses = (
            db.session.query(EntityAddress)
            .filter(EntityAddress.entity_ulid == created.entity_ulid)
            .all()
        )
        assert addresses == []
