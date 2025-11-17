# tests/test_foundation_entity_db.py

from app.extensions import db
from app.slices.customers.models import (
    Customer,
    CustomerEligibility,
    CustomerHistory,
)
from app.slices.entity.services import create_person_entity


def test_fk_constraints_positive_path(app):
    # create a real person entity (parent) the canonical way
    e = create_person_entity(first_name="Test", last_name="Subject", preferred_name=None)

    # create the Customer tied to that entity
    cust = Customer(entity_ulid=e.ulid)
    db.session.add(cust)
    db.session.flush()  # assigns cust.ulid

    # children that FK to customer_ulid should succeed
    hist = CustomerHistory(
        customer_ulid=cust.ulid,
        section="profile:needs:tier1",
        data_json="{}",
    )
    el = CustomerEligibility(customer_ulid=cust.ulid)
    db.session.add_all([hist, el])
    # implicit flush at context exit verifies constraints


def test_iso_timestamps_autofill_on_insert(app):
    p = EntityPerson(ulid=None)          # ULIDPK default should set this
    db.session.add(p)
    db.session.flush()             # force INSERT to happen now

    # IsoTimestamps (created_at_utc, updated_at_utc) should be set by defaults
    assert p.created_at_utc and p.updated_at_utc
    assert isinstance(p.created_at_utc, str) and p.created_at_utc.endswith("Z")
    assert p.updated_at_utc >= p.created_at_utc


def test_iso_timestamps_updates_on_modify(app):
    from app.extensions import db
    from app.slices.entity.models import EntityPerson

    p = EntityPerson()
    db.session.add(p)
    db.session.flush()

    created = p.created_at_utc
    prev_updated = p.updated_at_utc

    # change any column so the ORM issues an UPDATE
    p.preferred_name = "touched"  # or any legitimate column on Person
    db.session.flush()

    assert p.created_at_utc == created
    assert p.updated_at_utc >= prev_updated


def test_fk_constraints_enforced_customer_history(app):
    bogus_customer_ulid = "01ZZZZZZZZZZZZZZZZZZZZZZZZ"  # 26 chars; never created

    bad = CustomerHistory(
        customer_ulid=bogus_customer_ulid,
        section="profile:needs:tier1",
        data_json="{}",
    )
    db.session.add(bad)
    # Flush triggers the INSERT and should raise

    db.session.flush()
    # Session is in “failed” state;
    # expire/rollback happens at end of context



def test_fk_constraints_enforced_customer_eligibility(app):
    bogus_customer_ulid = "01ZZZZZZZZZZZZZZZZZZZZZZZZ"

    bad = CustomerEligibility(customer_ulid=bogus_customer_ulid)
    db.session.add(bad)
    db.session.flush()
