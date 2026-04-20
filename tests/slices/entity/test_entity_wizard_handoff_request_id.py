from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.entity import routes_wizard
from app.slices.entity.models import Entity, EntityPerson, EntityRole


def _make_person_entity(
    *,
    intake_request_id: str,
    intake_step: str,
) -> Entity:
    ent = Entity(
        kind="person",
        intake_step=intake_step,
        intake_request_id=intake_request_id,
    )
    ent.person = EntityPerson(first_name="Handoff", last_name="Trace")
    db.session.add(ent)
    db.session.commit()
    return ent


def _capture_wizard_next(app, monkeypatch, entity_ulid: str):
    captured: dict = {}

    def fake_render(template_name: str, **context):
        captured["template_name"] = template_name
        captured["context"] = context
        return "OK"

    monkeypatch.setattr(routes_wizard, "render_template", fake_render)

    with app.test_request_context(f"/entity/wizard/{entity_ulid}/next"):
        response = routes_wizard.wizard_next.__wrapped__(entity_ulid)

    assert response == "OK"
    return captured["context"]["actions"]


def test_customer_handoff_action_carries_persisted_request_id(
    app, monkeypatch
):
    with app.app_context():
        rid = new_ulid()
        ent = _make_person_entity(
            intake_request_id=rid,
            intake_step="handoff",
        )
        db.session.add(EntityRole(entity_ulid=ent.ulid, role="customer"))
        db.session.commit()

        actions = _capture_wizard_next(app, monkeypatch, ent.ulid)

        urls = [a["url"] for a in actions if "Customer Intake" in a["label"]]
        assert len(urls) == 1
        parsed = urlparse(urls[0])
        qs = parse_qs(parsed.query)

        assert parsed.path.endswith(f"/{ent.ulid}")
        assert qs["request_id"] == [rid]


def test_resource_and_sponsor_handoff_actions_carry_persisted_request_id(
    app,
    monkeypatch,
):
    with app.app_context():
        rid = new_ulid()
        ent = _make_person_entity(
            intake_request_id=rid,
            intake_step="handoff",
        )
        db.session.add(EntityRole(entity_ulid=ent.ulid, role="resource"))
        db.session.add(EntityRole(entity_ulid=ent.ulid, role="sponsor"))
        db.session.commit()

        actions = _capture_wizard_next(app, monkeypatch, ent.ulid)

        resource_urls = [
            a["url"] for a in actions if "Resource Onboarding" in a["label"]
        ]
        sponsor_urls = [
            a["url"] for a in actions if "Sponsor Onboarding" in a["label"]
        ]

        assert len(resource_urls) == 1
        assert len(sponsor_urls) == 1
        assert f"entity_ulid={ent.ulid}" in resource_urls[0]
        assert f"request_id={rid}" in resource_urls[0]
        assert f"entity_ulid={ent.ulid}" in sponsor_urls[0]
        assert f"request_id={rid}" in sponsor_urls[0]


def test_streamless_person_poc_actions_carry_persisted_request_id(
    app, monkeypatch
):
    with app.app_context():
        rid = new_ulid()
        ent = _make_person_entity(
            intake_request_id=rid,
            intake_step="handoff",
        )

        actions = _capture_wizard_next(app, monkeypatch, ent.ulid)

        resource_poc_urls = [
            a["url"] for a in actions if "Resource POC" in a["label"]
        ]
        sponsor_poc_urls = [
            a["url"] for a in actions if "Sponsor POC" in a["label"]
        ]

        assert len(resource_poc_urls) == 1
        assert len(sponsor_poc_urls) == 1
        parsed_resource = urlparse(resource_poc_urls[0])
        qs_resource = parse_qs(parsed_resource.query)

        assert parsed_resource.path.endswith(f"/{ent.ulid}")
        assert qs_resource["request_id"] == [rid]

        parsed_sponsor = urlparse(sponsor_poc_urls[0])
        qs_sponsor = parse_qs(parsed_sponsor.query)

        assert parsed_sponsor.path.endswith(f"/{ent.ulid}")
        assert qs_sponsor["request_id"] == [rid]
