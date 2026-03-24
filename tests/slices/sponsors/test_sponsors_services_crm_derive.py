# tests/slices/sponsors/test_sponsors_services_crm_derive.py

from __future__ import annotations

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import (
    FundingProspect,
    Sponsor,
    SponsorFundingIntent,
)
from app.slices.sponsors.services import (
    upsert_capabilities,
    upsert_donation_restrictions,
)
from app.slices.sponsors.services_crm import (
    derive_crm_factors_from_history,
    get_crm_factors,
    set_crm_factors,
    sync_derived_crm_factors,
)


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


def test_derive_crm_factors_from_capabilities_and_restrictions(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Derive Caps Sponsor")

        out1 = upsert_capabilities(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "funding.cash_grant": True,
                "funding.restricted_grant": True,
                "in_kind.in_kind_goods": True,
                "in_kind.in_kind_services": True,
            },
            actor_ulid=None,
            request_id="req-crm-derive-caps-1",
        )
        db.session.flush()
        assert out1 is not None

        out2 = upsert_donation_restrictions(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "restrictions.local": True,
                "restrictions.veteran": True,
                "restrictions.unrestricted": True,
            },
            actor_ulid=None,
            request_id="req-crm-derive-caps-2",
        )
        db.session.flush()
        assert out2 is not None

        derived = derive_crm_factors_from_history(sponsor.entity_ulid)

        assert set(derived.keys()) == {
            "style_cash_grant",
            "style_in_kind_goods",
            "style_service_support",
            "restriction_purpose_bound",
            "restriction_flexible",
            "restriction_geo_local_only",
            "restriction_population_veterans_only",
        }

        assert derived["style_cash_grant"]["source"] == "inferred"
        assert derived["restriction_purpose_bound"]["source"] == "inferred"
        assert derived["restriction_flexible"]["source"] == "inferred"
        assert derived["style_cash_grant"]["strength"] == "observed"


def test_derive_crm_factors_from_intent_history(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Derive Intent Sponsor")

        db.session.add_all(
            [
                SponsorFundingIntent(
                    sponsor_entity_ulid=sponsor.entity_ulid,
                    funding_demand_ulid="01AAAAAAAAAAAAAAAAAAAAAAAA",
                    intent_kind="pledge",
                    amount_cents=50000,
                    status="fulfilled",
                ),
                SponsorFundingIntent(
                    sponsor_entity_ulid=sponsor.entity_ulid,
                    funding_demand_ulid="01BBBBBBBBBBBBBBBBBBBBBBBB",
                    intent_kind="pledge",
                    amount_cents=65000,
                    status="fulfilled",
                ),
            ]
        )
        db.session.flush()

        derived = derive_crm_factors_from_history(sponsor.entity_ulid)

        assert derived["relationship_prior_success"]["source"] == "inferred"
        assert derived["relationship_repeat_supporter"]["strength"] == (
            "recurring"
        )
        assert (
            derived["relationship_follow_through_strong"]["strength"]
            == "strong_pattern"
        )
        assert "relationship_follow_through_mixed" not in derived
        assert "relationship_new_prospect" not in derived


def test_derive_crm_factors_marks_new_prospect_when_pipeline_exists_without_success(
    app,
):
    with app.app_context():
        sponsor = _create_sponsor("CRM Derive Prospect Sponsor")

        db.session.add(
            FundingProspect(
                sponsor_entity_ulid=sponsor.entity_ulid,
                project_type_key="operations",
                fund_archetype_key="general_unrestricted",
                label="Small Community Grant",
                confidence=55,
                status="prospect",
            )
        )
        db.session.flush()

        derived = derive_crm_factors_from_history(sponsor.entity_ulid)

        assert set(derived.keys()) == {"relationship_new_prospect"}
        assert derived["relationship_new_prospect"]["source"] == "inferred"


def test_sync_derived_crm_factors_writes_inferred_factors(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Sync Derived Sponsor")

        out1 = upsert_capabilities(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "funding.cash_grant": True,
                "in_kind.in_kind_goods": True,
            },
            actor_ulid=None,
            request_id="req-crm-sync-derive-1",
        )
        db.session.flush()
        assert out1 is not None

        hist_ulid = sync_derived_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            actor_ulid=None,
            request_id="req-crm-sync-derive-2",
        )
        db.session.flush()

        assert hist_ulid is not None

        snap = get_crm_factors(sponsor.entity_ulid)
        assert snap["style_cash_grant"]["source"] == "inferred"
        assert snap["style_in_kind_goods"]["source"] == "inferred"


def test_sync_derived_crm_factors_does_not_overwrite_operator_factor(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Sync Preserve Operator Sponsor")

        out1 = upsert_capabilities(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "funding.cash_grant": True,
            },
            actor_ulid=None,
            request_id="req-crm-sync-preserve-1",
        )
        db.session.flush()
        assert out1 is not None

        out2 = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "style_cash_grant": {
                    "has": True,
                    "strength": "strong_pattern",
                    "source": "operator",
                    "note": "Known dependable donor style.",
                }
            },
            actor_ulid=None,
            request_id="req-crm-sync-preserve-2",
        )
        db.session.flush()
        assert out2 is not None

        out3 = sync_derived_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            actor_ulid=None,
            request_id="req-crm-sync-preserve-3",
        )
        db.session.flush()

        # no change needed because inferred should not stomp operator
        assert out3 is None

        snap = get_crm_factors(sponsor.entity_ulid)
        assert snap["style_cash_grant"]["source"] == "operator"
        assert snap["style_cash_grant"]["strength"] == "strong_pattern"
        assert snap["style_cash_grant"]["note"] == (
            "Known dependable donor style."
        )


def test_sync_derived_crm_factors_removes_stale_inferred_keys(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Sync Remove Stale Sponsor")

        out1 = upsert_capabilities(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "funding.cash_grant": True,
            },
            actor_ulid=None,
            request_id="req-crm-sync-stale-1",
        )
        db.session.flush()
        assert out1 is not None

        out2 = sync_derived_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            actor_ulid=None,
            request_id="req-crm-sync-stale-2",
        )
        db.session.flush()
        assert out2 is not None

        snap1 = get_crm_factors(sponsor.entity_ulid)
        assert "style_cash_grant" in snap1
        assert snap1["style_cash_grant"]["source"] == "inferred"

        out3 = upsert_capabilities(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={},
            actor_ulid=None,
            request_id="req-crm-sync-stale-3",
        )
        db.session.flush()
        assert out3 is not None

        out4 = sync_derived_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            actor_ulid=None,
            request_id="req-crm-sync-stale-4",
        )
        db.session.flush()
        assert out4 is not None

        snap2 = get_crm_factors(sponsor.entity_ulid)
        assert "style_cash_grant" not in snap2
