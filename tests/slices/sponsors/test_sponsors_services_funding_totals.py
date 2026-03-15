# tests/slices/sponsors/test_sponsors_services_funding_totals.py

from __future__ import annotations

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import Sponsor, SponsorFundingIntent
from app.slices.sponsors.services_funding import get_funding_intent_totals


def create_sponsor(name: str) -> Sponsor:
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


def test_get_funding_intent_totals_groups_by_sponsor(app, ulid):
    with app.app_context():
        s1 = create_sponsor("Sponsor A")
        s2 = create_sponsor("Sponsor B")
        demand_ulid = ulid()

        db.session.add_all(
            [
                SponsorFundingIntent(
                    sponsor_entity_ulid=s1.entity_ulid,
                    funding_demand_ulid=demand_ulid,
                    intent_kind="pledge",
                    amount_cents=5000,
                    status="committed",
                ),
                SponsorFundingIntent(
                    sponsor_entity_ulid=s2.entity_ulid,
                    funding_demand_ulid=demand_ulid,
                    intent_kind="pledge",
                    amount_cents=3000,
                    status="committed",
                ),
            ]
        )
        db.session.commit()

        out = get_funding_intent_totals(demand_ulid)

        assert out["funding_demand_ulid"] == demand_ulid
        assert out["pledged_cents"] == 8000

        by_key = {
            row["key"]: row["amount_cents"]
            for row in out["pledged_by_sponsor"]
        }
        assert by_key[s1.entity_ulid] == 5000
        assert by_key[s2.entity_ulid] == 3000
        assert len(out["pledge_ulids"]) == 2
        assert len(out["donation_ulids"]) == 0
