# tests/slices/customers/test_customer_history_on_needs_complete.py

from sqlalchemy import select

from app.extensions import db
from app.slices.customers import services as svc
from app.slices.customers.models import (
    Customer,
    CustomerEligibility,
    CustomerHistory,
    CustomerProfile,
    CustomerProfileRating,
)
from app.lib.ids import new_ulid
from app.slices.entity.models import Entity, EntityPerson

TIER1 = ("food", "hygiene", "health", "housing", "clothing")
TIER2 = ("income", "employment", "transportation", "education")
TIER3 = ("family", "peergroup", "tech")
ALL_KEYS = TIER1 + TIER2 + TIER3


def _seed_entity_person(
    entity_ulid: str,
    *,
    first_name: str = "Test",
    last_name: str = "User",
) -> None:
    ent = Entity(
        ulid=entity_ulid,
        kind="person",
    )
    person = EntityPerson(
        entity_ulid=entity_ulid,
        first_name=first_name,
        last_name=last_name,
        preferred_name=None,
        last_4=None,
        dob=None,
    )
    db.session.add(ent)
    db.session.add(person)
    db.session.flush()


def _seed_actor_entity(actor_ulid: str) -> None:
    _seed_entity_person(
        actor_ulid,
        first_name="Op",
        last_name="Erator",
    )


def _seed_ready_customer(entity_ulid: str, actor_ulid: str) -> None:
    _seed_entity_person(
        entity_ulid,
        first_name="Test",
        last_name="User",
    )

    c = Customer(
        entity_ulid=entity_ulid,
        status="intake",
        intake_step="review",
        eligibility_complete=True,
        tier1_assessed=True,
        tier2_assessed=True,
        tier3_assessed=True,
        tier1_unlocked=True,
        tier2_unlocked=True,
        tier3_unlocked=True,
        assessment_complete=True,
        tier1_min=1,
        tier2_min=2,
        tier3_min=3,
        flag_tier1_immediate=True,
        watchlist=False,
    )
    e = CustomerEligibility(
        entity_ulid=entity_ulid,
        veteran_status="verified",
        veteran_method="dd214",
        branch="USA",
        era="ColdWar",
        housing_status="housed",
        approved_by_ulid=None,
        approved_at_iso=None,
    )
    p = CustomerProfile(
        entity_ulid=entity_ulid,
        assessment_version=1,
        last_assessed_at_iso=None,
        last_assessed_by_ulid=None,
    )

    db.session.add_all([c, e, p])

    ratings = []
    values = {
        "food": "immediate",
        "hygiene": "marginal",
        "health": "sufficient",
        "housing": "marginal",
        "clothing": "marginal",
        "income": "marginal",
        "employment": "marginal",
        "transportation": "immediate",
        "education": "marginal",
        "family": "not_applicable",
        "peergroup": "sufficient",
        "tech": "immediate",
    }
    for key in ALL_KEYS:
        ratings.append(
            CustomerProfileRating(
                entity_ulid=entity_ulid,
                assessment_version=1,
                category_key=key,
                is_assessed=True,
                rating_value=values[key],
            )
        )
    db.session.add_all(ratings)
    db.session.flush()


def test_needs_complete_initial_appends_history_and_emits(app, monkeypatch):
    captured = []

    def fake_emit(**kwargs):
        captured.append(kwargs)

    with app.app_context():
        monkeypatch.setattr(svc.event_bus, "emit", fake_emit)

        db.session.rollback()

        entity_ulid = new_ulid()
        actor_ulid = new_ulid()
        request_id = new_ulid()

        _seed_ready_customer(entity_ulid, actor_ulid)

        result = svc.needs_complete(
            entity_ulid=entity_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        assert result.noop is False
        assert result.entity_ulid == entity_ulid

        c = db.session.get(Customer, entity_ulid)
        p = db.session.get(CustomerProfile, entity_ulid)

        assert c is not None
        assert p is not None
        assert c.intake_step == "complete"
        assert c.status == "active"
        assert c.intake_completed_at_iso is not None
        assert p.last_assessed_at_iso is not None
        assert p.last_assessed_by_ulid == actor_ulid

        rows = (
            db.session.execute(
                select(CustomerHistory).where(
                    CustomerHistory.entity_ulid == entity_ulid
                )
            )
            .scalars()
            .all()
        )

        assert len(rows) == 1
        row = rows[0]
        assert row.kind == "assessment.initial"
        assert row.source_slice == "customers"
        assert row.schema_name == "customers.assessment.synopsis.v1"
        assert row.created_by_actor_ulid == actor_ulid

        # one emit from append_history_entry + one emit from needs_complete
        ops = [x["operation"] for x in captured]
        assert ops == [
            "customer_history_appended",
            "customer_needs_completed",
        ]

        completed_emit = captured[-1]
        assert completed_emit["refs"]["assessment_version"] == 1
        assert completed_emit["refs"]["history_ulid"] == row.ulid


def test_needs_complete_incomplete_assessment_writes_nothing(
    app, monkeypatch
):
    captured = []

    def fake_emit(**kwargs):
        captured.append(kwargs)

    with app.app_context():
        monkeypatch.setattr(svc.event_bus, "emit", fake_emit)

        db.session.rollback()

        entity_ulid = new_ulid()
        actor_ulid = new_ulid()
        request_id = new_ulid()

        _seed_entity_person(
            entity_ulid,
            first_name="Test",
            last_name="User",
        )
        _seed_actor_entity(actor_ulid)

        c = Customer(
            entity_ulid=entity_ulid,
            status="intake",
            intake_step="review",
            eligibility_complete=True,
            tier1_assessed=True,
            tier2_assessed=False,
            tier3_assessed=False,
            tier1_unlocked=True,
            tier2_unlocked=False,
            tier3_unlocked=False,
            assessment_complete=False,
            tier1_min=1,
            tier2_min=None,
            tier3_min=None,
            flag_tier1_immediate=True,
            watchlist=False,
        )
        e = CustomerEligibility(
            entity_ulid=entity_ulid,
            veteran_status="verified",
            veteran_method="dd214",
            branch="USA",
            era="ColdWar",
            housing_status="housed",
        )
        p = CustomerProfile(
            entity_ulid=entity_ulid,
            assessment_version=1,
        )
        db.session.add_all([c, e, p])
        db.session.flush()

        import pytest

        with pytest.raises(ValueError, match="assessment not complete"):
            svc.needs_complete(
                entity_ulid=entity_ulid,
                request_id=request_id,
                actor_ulid=actor_ulid,
            )

        db.session.rollback()

        rows = (
            db.session.execute(
                select(CustomerHistory).where(
                    CustomerHistory.entity_ulid == entity_ulid
                )
            )
            .scalars()
            .all()
        )

        assert rows == []
        assert captured == []


def test_needs_complete_reassessment_uses_reassessment_kind(app, monkeypatch):
    captured = []

    def fake_emit(**kwargs):
        captured.append(kwargs)

    with app.app_context():
        monkeypatch.setattr(svc.event_bus, "emit", fake_emit)

        db.session.rollback()

        entity_ulid = new_ulid()
        actor_ulid = new_ulid()
        request_id = new_ulid()

        _seed_ready_customer(entity_ulid, actor_ulid)

        p = db.session.get(CustomerProfile, entity_ulid)
        assert p is not None
        p.assessment_version = 2
        db.session.execute(
            select(CustomerProfileRating).where(
                CustomerProfileRating.entity_ulid == entity_ulid
            )
        ).scalars().delete if False else None
        # easiest path: replace rows for version 2
        db.session.query(CustomerProfileRating).filter_by(
            entity_ulid=entity_ulid
        ).delete()

        for key, value in {
            "food": "marginal",
            "hygiene": "marginal",
            "health": "sufficient",
            "housing": "marginal",
            "clothing": "marginal",
            "income": "marginal",
            "employment": "marginal",
            "transportation": "marginal",
            "education": "marginal",
            "family": "not_applicable",
            "peergroup": "sufficient",
            "tech": "sufficient",
        }.items():
            db.session.add(
                CustomerProfileRating(
                    entity_ulid=entity_ulid,
                    assessment_version=2,
                    category_key=key,
                    is_assessed=True,
                    rating_value=value,
                )
            )
        db.session.flush()

        svc.needs_complete(
            entity_ulid=entity_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        db.session.commit()

        row = db.session.execute(
            select(CustomerHistory).where(
                CustomerHistory.entity_ulid == entity_ulid
            )
        ).scalar_one()

        assert row.kind == "assessment.reassessment"
