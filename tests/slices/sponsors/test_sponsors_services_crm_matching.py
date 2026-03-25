# tests/slices/sponsors/test_sponsors_services_crm_matching.py

from __future__ import annotations

from app.extensions import db
from app.slices.calendar.models import Project
from app.slices.calendar.services_funding import (
    create_funding_demand,
    publish_funding_demand,
)
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.mapper import sponsor_opportunity_match_to_dto
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services import set_profile_hints
from app.slices.sponsors.services_crm import (
    compute_opportunity_match,
    list_opportunity_matches,
    set_crm_factors,
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


def _create_published_demand(
    *,
    title: str,
    spending_class: str,
    tag_any: str,
) -> str:
    project = Project(
        project_title=f"{title} Project",
        status="planned",
    )
    db.session.add(project)
    db.session.flush()

    row = create_funding_demand(
        {
            "project_ulid": project.ulid,
            "title": title,
            "goal_cents": 25000,
            "deadline_date": "2026-04-15",
            "spending_class": spending_class,
            "tag_any": tag_any,
        },
        actor_ulid=None,
        request_id=f"req-match-create-{title}",
    )
    db.session.flush()

    row = publish_funding_demand(
        row.ulid,
        actor_ulid=None,
        request_id=f"req-match-publish-{title}",
    )
    db.session.flush()
    return row.ulid


def test_compute_opportunity_match_likely_fit(app, monkeypatch):
    from app.slices.calendar import services_funding as cal_svc

    monkeypatch.setattr(
        cal_svc,
        "_project_policy_hints",
        lambda project_ulid: cal_svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        demand_ulid = _create_published_demand(
            title="Likely Fit Demand",
            spending_class="basic_needs",
            tag_any="crm_seed",
        )
        sponsor = _create_sponsor("Likely Fit Sponsor")

        out = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": True,
                "mission_basic_needs": True,
                "style_cash_grant": True,
                "restriction_geo_local_only": True,
                "restriction_population_veterans_only": True,
                "relationship_prior_success": True,
            },
            actor_ulid=None,
            request_id="req-match-likely-1",
        )
        db.session.flush()
        assert out is not None

        note_out = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "relationship_note": "Warm history with veteran-focused asks.",
            },
            actor_ulid=None,
            request_id="req-match-likely-2",
        )
        db.session.flush()
        assert note_out is not None

        view = compute_opportunity_match(
            sponsor_entity_ulid=sponsor.entity_ulid,
            funding_demand_ulid=demand_ulid,
        )

        assert view.fit_band == "likely_fit"
        assert view.manual_review_recommended is False
        assert view.suggested_next_action == "proceed_outreach"
        assert len(view.positive_reasons) >= 3
        assert any(
            "Mission alignment" in reason for reason in view.positive_reasons
        )
        assert any(
            "Prior successful support exists." == reason
            for reason in view.positive_reasons
        )
        assert len(view.caution_reasons) == 0
        assert len(view.profile_note_hints) == 1
        assert view.profile_note_hints[0].key == "relationship_note"


def test_compute_opportunity_match_caution_and_manual_review(
    app, monkeypatch
):
    from app.slices.calendar import services_funding as cal_svc

    monkeypatch.setattr(
        cal_svc,
        "_project_policy_hints",
        lambda project_ulid: cal_svc.ProjectPolicyHints(
            source_profile_key="welcome_home_reimbursement_bridgeable",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        demand_ulid = _create_published_demand(
            title="Caution Demand",
            spending_class="basic_needs",
            tag_any="welcome_home_kit",
        )
        sponsor = _create_sponsor("Caution Sponsor")

        out = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "restriction_geo_local_only": True,
                "friction_board_review": True,
                "relationship_prior_decline": True,
            },
            actor_ulid=None,
            request_id="req-match-caution-1",
        )
        db.session.flush()
        assert out is not None

        view = compute_opportunity_match(
            sponsor_entity_ulid=sponsor.entity_ulid,
            funding_demand_ulid=demand_ulid,
        )

        assert view.fit_band == "caution"
        assert view.manual_review_recommended is True
        assert view.suggested_next_action == "manual_review"
        assert any(
            reason == "Sponsor often expects local-only scope."
            for reason in view.caution_reasons
        )
        assert any(
            reason == "Board review commonly required."
            for reason in view.caution_reasons
        )
        assert any(
            reason == "Prior decline history exists."
            for reason in view.caution_reasons
        )


def test_list_opportunity_matches_sorts_likely_before_caution(
    app, monkeypatch
):
    from app.slices.calendar import services_funding as cal_svc

    monkeypatch.setattr(
        cal_svc,
        "_project_policy_hints",
        lambda project_ulid: cal_svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        demand_ulid = _create_published_demand(
            title="Sorted Demand",
            spending_class="basic_needs",
            tag_any="crm_seed",
        )

        likely = _create_sponsor("Likely Sort Sponsor")
        caution = _create_sponsor("Caution Sort Sponsor")

        out1 = set_crm_factors(
            sponsor_entity_ulid=likely.entity_ulid,
            payload={
                "mission_local_veterans": True,
                "mission_basic_needs": True,
                "style_cash_grant": True,
                "relationship_prior_success": True,
                "restriction_geo_local_only": True,
                "restriction_population_veterans_only": True,
            },
            actor_ulid=None,
            request_id="req-match-sort-1",
        )
        db.session.flush()
        assert out1 is not None

        out2 = set_crm_factors(
            sponsor_entity_ulid=caution.entity_ulid,
            payload={
                "friction_board_review": True,
                "relationship_prior_decline": True,
            },
            actor_ulid=None,
            request_id="req-match-sort-2",
        )
        db.session.flush()
        assert out2 is not None

        rows = list_opportunity_matches(demand_ulid)

        assert len(rows) >= 2
        likely_ix = next(
            i
            for i, row in enumerate(rows)
            if row.sponsor_entity_ulid == likely.entity_ulid
        )
        caution_ix = next(
            i
            for i, row in enumerate(rows)
            if row.sponsor_entity_ulid == caution.entity_ulid
        )
        assert likely_ix < caution_ix
        assert rows[likely_ix].fit_band == "likely_fit"

        caution_row = next(
            row
            for row in rows
            if row.sponsor_entity_ulid == caution.entity_ulid
        )
        assert caution_row.fit_band == "caution"


def test_sponsor_opportunity_match_to_dto_shapes_output(app, monkeypatch):
    from app.slices.calendar import services_funding as cal_svc

    monkeypatch.setattr(
        cal_svc,
        "_project_policy_hints",
        lambda project_ulid: cal_svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        demand_ulid = _create_published_demand(
            title="DTO Demand",
            spending_class="basic_needs",
            tag_any="crm_seed",
        )
        sponsor = _create_sponsor("DTO Match Sponsor")

        out = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": True,
                "relationship_prior_success": True,
            },
            actor_ulid=None,
            request_id="req-match-dto-1",
        )
        db.session.flush()
        assert out is not None

        note_out = set_profile_hints(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "recognition_note": "Prefers simple public thanks.",
            },
            actor_ulid=None,
            request_id="req-match-dto-2",
        )
        db.session.flush()
        assert note_out is not None

        view = compute_opportunity_match(
            sponsor_entity_ulid=sponsor.entity_ulid,
            funding_demand_ulid=demand_ulid,
        )
        dto = sponsor_opportunity_match_to_dto(view)

        assert dto["sponsor_entity_ulid"] == sponsor.entity_ulid
        assert dto["funding_demand_ulid"] == demand_ulid
        assert dto["fit_band"] in {"likely_fit", "maybe_fit", "caution"}
        assert isinstance(dto["positive_reasons"], list)
        assert isinstance(dto["caution_reasons"], list)
        assert isinstance(dto["profile_note_hints"], list)
        assert dto["profile_note_hints"][0]["key"] == "recognition_note"
