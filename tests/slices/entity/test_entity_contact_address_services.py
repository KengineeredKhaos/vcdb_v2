from __future__ import annotations

from app.extensions import db
from app.slices.entity import services as svc
from app.slices.entity.models import EntityAddress, EntityContact


def _make_person(*, request_id: str) -> str:
    dto = svc.create_operator_core(
        first_name="Mike",
        last_name="Shaw",
        preferred_name="Mike",
        request_id=request_id,
        actor_ulid=None,
    )
    return dto.entity_ulid


def test_edit_contact_writes_primary_email_and_phone_rows_and_summary(app):
    with app.app_context():
        entity_ulid = _make_person(request_id="ent-contact-001")

        svc.edit_contact(
            entity_ulid=entity_ulid,
            email="mike@example.org",
            phone="5551112222",
            request_id="ent-contact-002",
            actor_ulid=None,
        )

        rows = (
            db.session.query(EntityContact)
            .filter_by(entity_ulid=entity_ulid)
            .filter(EntityContact.archived_at.is_(None))
            .all()
        )
        assert len(rows) == 2
        assert sum(1 for row in rows if row.is_primary) == 2
        assert sum(1 for row in rows if row.email) == 1
        assert sum(1 for row in rows if row.phone) == 1

        summary = svc.get_entity_contact_summary(
            entity_ulids=[entity_ulid]
        )[entity_ulid]
        email_row = next(row for row in rows if row.email)
        phone_row = next(row for row in rows if row.phone)

        assert summary.primary_email == email_row.email
        assert summary.primary_phone == phone_row.phone


def test_set_contact_primary_demotes_only_conflicting_type(app):
    with app.app_context():
        entity_ulid = _make_person(request_id="ent-contact-101")

        email_1 = svc.add_contact(
            entity_ulid=entity_ulid,
            email="primary@example.org",
            is_primary=True,
            request_id="ent-contact-102",
            actor_ulid=None,
        )
        phone_1 = svc.add_contact(
            entity_ulid=entity_ulid,
            phone="5551113333",
            is_primary=True,
            request_id="ent-contact-103",
            actor_ulid=None,
        )
        email_2 = svc.add_contact(
            entity_ulid=entity_ulid,
            email="backup@example.org",
            is_primary=False,
            request_id="ent-contact-104",
            actor_ulid=None,
        )

        changed = svc.set_contact_primary(
            contact_ulid=email_2,
            request_id="ent-contact-105",
            actor_ulid=None,
        )
        assert changed is True

        first_email = db.session.get(EntityContact, email_1)
        second_email = db.session.get(EntityContact, email_2)
        first_phone = db.session.get(EntityContact, phone_1)

        assert first_email is not None and first_email.is_primary is False
        assert second_email is not None and second_email.is_primary is True
        assert first_phone is not None and first_phone.is_primary is True

        summary = svc.get_entity_contact_summary(
            entity_ulids=[entity_ulid]
        )[entity_ulid]
        assert summary.primary_email == second_email.email
        assert summary.primary_phone == first_phone.phone


def test_archive_contact_removes_archived_row_from_summary(app):
    with app.app_context():
        entity_ulid = _make_person(request_id="ent-contact-201")

        primary_email = svc.add_contact(
            entity_ulid=entity_ulid,
            email="primary@example.org",
            is_primary=True,
            request_id="ent-contact-202",
            actor_ulid=None,
        )
        backup_email = svc.add_contact(
            entity_ulid=entity_ulid,
            email="backup@example.org",
            is_primary=False,
            request_id="ent-contact-203",
            actor_ulid=None,
        )

        archived = svc.archive_contact(
            contact_ulid=primary_email,
            request_id="ent-contact-204",
            actor_ulid=None,
        )
        assert archived is True

        primary_row = db.session.get(EntityContact, primary_email)
        backup_row = db.session.get(EntityContact, backup_email)
        assert primary_row is not None and primary_row.archived_at is not None
        assert backup_row is not None and backup_row.archived_at is None

        summary = svc.get_entity_contact_summary(
            entity_ulids=[entity_ulid]
        )[entity_ulid]
        assert summary.primary_email == backup_row.email


def test_get_person_view_uses_primary_email_and_phone_across_separate_rows(app):
    with app.app_context():
        entity_ulid = _make_person(request_id="ent-contact-301")

        svc.add_contact(
            entity_ulid=entity_ulid,
            email="person@example.org",
            is_primary=True,
            request_id="ent-contact-302",
            actor_ulid=None,
        )
        svc.add_contact(
            entity_ulid=entity_ulid,
            phone="5551114444",
            is_primary=True,
            request_id="ent-contact-303",
            actor_ulid=None,
        )

        view = svc.get_person_view(entity_ulid)
        assert view is not None
        assert view["email"] == "person@example.org"
        assert view["phone"] is not None


def test_upsert_address_replaces_physical_and_preserves_postal(app):
    with app.app_context():
        entity_ulid = _make_person(request_id="ent-address-001")

        first_ulid = svc.upsert_address(
            entity_ulid=entity_ulid,
            is_physical=True,
            is_postal=True,
            address1="100 Main St",
            address2=None,
            city="Anytown",
            state="CA",
            postal_code="90210",
            request_id="ent-address-002",
            actor_ulid=None,
        )

        second_ulid = svc.upsert_address(
            entity_ulid=entity_ulid,
            is_physical=True,
            is_postal=False,
            address1="200 Oak Ave",
            address2="Unit B",
            city="Elsewhere",
            state="CA",
            postal_code="94110",
            request_id="ent-address-003",
            actor_ulid=None,
        )

        assert first_ulid != second_ulid

        active_rows = (
            db.session.query(EntityAddress)
            .filter_by(entity_ulid=entity_ulid)
            .filter(EntityAddress.archived_at.is_(None))
            .all()
        )
        assert len(active_rows) == 2

        summary = svc.get_entity_address_summary(
            entity_ulids=[entity_ulid]
        )[entity_ulid]

        assert summary.physical is not None
        assert summary.postal is not None
        assert summary.physical.address1 == "200 Oak Ave"
        assert summary.physical.address2 == "Unit B"
        assert summary.postal.address1 == "100 Main St"


def test_upsert_address_same_payload_can_serve_both_roles(app):
    with app.app_context():
        entity_ulid = _make_person(request_id="ent-address-101")

        first_ulid = svc.upsert_address(
            entity_ulid=entity_ulid,
            is_physical=True,
            is_postal=False,
            address1="300 Pine Rd",
            address2=None,
            city="Somewhere",
            state="CA",
            postal_code="95814",
            request_id="ent-address-102",
            actor_ulid=None,
        )

        second_ulid = svc.upsert_address(
            entity_ulid=entity_ulid,
            is_physical=False,
            is_postal=True,
            address1="300 Pine Rd",
            address2=None,
            city="Somewhere",
            state="CA",
            postal_code="95814",
            request_id="ent-address-103",
            actor_ulid=None,
        )

        assert first_ulid == second_ulid

        active_rows = (
            db.session.query(EntityAddress)
            .filter_by(entity_ulid=entity_ulid)
            .filter(EntityAddress.archived_at.is_(None))
            .all()
        )
        assert len(active_rows) == 1

        row = active_rows[0]
        assert row.is_physical is True
        assert row.is_postal is True

        summary = svc.get_entity_address_summary(
            entity_ulids=[entity_ulid]
        )[entity_ulid]
        assert summary.physical is not None
        assert summary.postal is not None
        assert summary.physical.address1 == "300 Pine Rd"
        assert summary.postal.address1 == "300 Pine Rd"
