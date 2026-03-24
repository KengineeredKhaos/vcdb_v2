# tests/slices/sponsors/test_sponsors_routes_detail.py

from __future__ import annotations

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services import set_profile_hints
from app.slices.sponsors.services_crm import set_crm_factors


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


def test_sponsor_detail_page_shows_posture_and_note_hints(app, staff_client):
    with app.app_context():
        sponsor = _create_sponsor("Detail Page Sponsor")

        out1 = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": True,
                "style_cash_grant": {
                    "has": True,
                    "strength": "strong_pattern",
                    "source": "operator",
                    "note": "Consistent direct-support pattern.",
                },
                "friction_board_review": {
                    "has": False,
                    "strength": "observed",
                    "source": "operator",
                    "note": "Not common now, but historically present.",
                },
            },
            actor_ulid=None,
            request_id="req-sponsor-detail-1",
        )
        db.session.flush()
        assert out1 is not None

        out2 = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_note": (
                    "Warm history with veteran-focused asks."
                ),
                "recognition_note": ("Prefers simple public acknowledgment."),
            },
            actor_ulid=None,
            request_id="req-sponsor-detail-2",
        )
        db.session.flush()
        assert out2 is not None

        db.session.commit()

    resp = staff_client.get(f"/sponsors/{sponsor.entity_ulid}/detail")
    assert resp.status_code == 200

    text = resp.get_data(as_text=True)
    assert "Sponsor Detail" in text
    assert "CRM posture" in text
    assert "Profile note hints" in text
    assert "Mission" in text
    assert "Style" in text
    assert "Friction" in text
    assert "Local veterans" in text
    assert "Cash grant" in text
    assert "Consistent direct-support pattern." in text
    assert "Warm history with veteran-focused asks." in text
    assert "Prefers simple public acknowledgment." in text
