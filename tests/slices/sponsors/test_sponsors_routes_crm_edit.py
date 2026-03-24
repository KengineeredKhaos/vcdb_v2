# tests/slices/sponsors/test_sponsors_routes_crm_edit.py

from __future__ import annotations

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_crm import get_crm_factors


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


def test_sponsor_crm_edit_page_renders(app, staff_client):
    with app.app_context():
        sponsor = _create_sponsor("CRM Edit Page Sponsor")
        db.session.commit()

    resp = staff_client.get(f"/sponsors/{sponsor.entity_ulid}/crm/edit")
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "Sponsor CRM Editor" in text
    assert "Mission" in text
    assert "Restriction" in text
    assert "Style" in text
    assert "Capacity" in text
    assert "Friction" in text
    assert "Relationship" in text
    assert "mission_local_veterans" in text
    assert "style_cash_grant" in text


def test_sponsor_crm_edit_save_updates_factor(app, staff_client):
    with app.app_context():
        sponsor = _create_sponsor("CRM Edit Save Sponsor")
        db.session.commit()

    resp = staff_client.post(
        f"/sponsors/{sponsor.entity_ulid}/crm/edit",
        data={
            "key": "style_cash_grant",
            "action": "save",
            "active": "on",
            "strength": "strong_pattern",
            "source": "operator",
            "note": "Reliable direct-support pattern.",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "CRM factor saved." in text
    assert "Reliable direct-support pattern." in text

    with app.app_context():
        snap = get_crm_factors(sponsor.entity_ulid)
        assert snap["style_cash_grant"]["has"] is True
        assert snap["style_cash_grant"]["strength"] == "strong_pattern"
        assert snap["style_cash_grant"]["source"] == "operator"
        assert snap["style_cash_grant"]["note"] == (
            "Reliable direct-support pattern."
        )


def test_sponsor_crm_edit_remove_deletes_factor(app, staff_client):
    with app.app_context():
        sponsor = _create_sponsor("CRM Edit Remove Sponsor")
        from app.slices.sponsors.services_crm import set_crm_factors

        out = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "friction_board_review": {
                    "has": True,
                    "strength": "observed",
                    "source": "operator",
                    "note": "Historically needed board review.",
                }
            },
            actor_ulid=None,
            request_id="req-crm-edit-remove-1",
        )
        db.session.flush()
        assert out is not None
        db.session.commit()

    resp = staff_client.post(
        f"/sponsors/{sponsor.entity_ulid}/crm/edit",
        data={
            "key": "friction_board_review",
            "action": "remove",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "CRM factor removed." in text

    with app.app_context():
        snap = get_crm_factors(sponsor.entity_ulid)
        assert "friction_board_review" not in snap
