from __future__ import annotations

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.entity import services_wizard as wiz
from app.slices.entity.models import Entity, EntityPerson, EntityRole


def _make_person_entity(
    *,
    intake_step: str,
    intake_request_id: str,
) -> Entity:
    ent = Entity(
        kind="person",
        intake_step=intake_step,
        intake_request_id=intake_request_id,
    )
    ent.person = EntityPerson(first_name="Trace", last_name="Target")
    db.session.add(ent)
    db.session.commit()
    return ent


def test_contact_emit_reuses_persisted_request_id(app, monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        wiz.event_bus,
        "emit",
        lambda **payload: emitted.append(payload),
    )

    with app.app_context():
        persisted_rid = new_ulid()
        fresh_rid = new_ulid()
        actor_ulid = new_ulid()
        ent = _make_person_entity(
            intake_step=wiz.INTAKE_STEP_CONTACT,
            intake_request_id=persisted_rid,
        )

        dto = wiz.wizard_contact(
            entity_ulid=ent.ulid,
            email="trace@example.org",
            phone=None,
            request_id=fresh_rid,
            actor_ulid=actor_ulid,
        )
        db.session.commit()
        db.session.refresh(ent)

        assert dto.intake_request_id == persisted_rid
        assert ent.intake_request_id == persisted_rid
        assert len(emitted) == 1
        assert emitted[0]["request_id"] == persisted_rid
        assert emitted[0]["actor_ulid"] == actor_ulid
        assert emitted[0]["target_ulid"] == ent.ulid


def test_existing_role_keeps_request_id_and_emits_nothing(app, monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        wiz.event_bus,
        "emit",
        lambda **payload: emitted.append(payload),
    )

    monkeypatch.setattr(
        wiz.governance_v2,
        "list_entity_role_codes",
        lambda: ["civilian"],
    )

    with app.app_context():
        persisted_rid = new_ulid()
        ent = _make_person_entity(
            intake_step=wiz.INTAKE_STEP_ROLE,
            intake_request_id=persisted_rid,
        )
        db.session.add(EntityRole(entity_ulid=ent.ulid, role="civilian"))
        db.session.commit()

        dto = wiz.wizard_set_single_role(
            entity_ulid=ent.ulid,
            role="civilian",
            request_id=new_ulid(),
            actor_ulid=new_ulid(),
        )
        db.session.commit()
        db.session.refresh(ent)

        assert dto.changed_fields == ()
        assert dto.intake_step == wiz.INTAKE_STEP_HANDOFF
        assert dto.intake_request_id == persisted_rid
        assert ent.intake_step == wiz.INTAKE_STEP_HANDOFF
        assert ent.intake_request_id == persisted_rid
        assert emitted == []


def test_role_emit_uses_persisted_request_id(app, monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        wiz.event_bus,
        "emit",
        lambda **payload: emitted.append(payload),
    )

    monkeypatch.setattr(
        wiz.governance_v2,
        "list_entity_role_codes",
        lambda: ["civilian"],
    )

    with app.app_context():
        persisted_rid = new_ulid()
        actor_ulid = new_ulid()
        ent = _make_person_entity(
            intake_step=wiz.INTAKE_STEP_ROLE,
            intake_request_id=persisted_rid,
        )

        dto = wiz.wizard_set_single_role(
            entity_ulid=ent.ulid,
            role="civilian",
            request_id=new_ulid(),
            actor_ulid=actor_ulid,
        )
        db.session.commit()
        db.session.refresh(ent)

        assert dto.intake_step == wiz.INTAKE_STEP_HANDOFF
        assert dto.intake_request_id == persisted_rid
        assert ent.intake_step == wiz.INTAKE_STEP_HANDOFF
        assert ent.intake_request_id == persisted_rid
        assert len(emitted) == 1
        assert emitted[0]["request_id"] == persisted_rid
        assert emitted[0]["actor_ulid"] == actor_ulid
        assert emitted[0]["target_ulid"] == ent.ulid
