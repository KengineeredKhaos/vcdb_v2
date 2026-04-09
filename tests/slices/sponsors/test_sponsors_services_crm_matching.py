# tests/slices/sponsors/test_sponsors_services_crm_matching.py

from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import governance_v2
from app.slices.calendar.models import Project
from app.slices.calendar.services_budget import (
    add_budget_line,
    create_working_snapshot,
    lock_snapshot,
)
from app.slices.calendar.services_drafts import (
    approve_draft_for_publish,
    create_draft_from_snapshot,
    mark_draft_ready_for_review,
    promote_draft_to_funding_demand,
    submit_draft_for_governance_review,
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
    source_profile_key: str = "mission_local_veterans_cash",
    default_restriction_keys: tuple[str, ...] = (
        "local_only",
        "vet_only",
    ),
    eligible_fund_codes: tuple[str, ...] = ("general_unrestricted",),
) -> str:
    project = Project(
        project_title=f"{title} Project",
        status="draft_planning",
        funding_profile_key=source_profile_key,
    )
    db.session.add(project)
    db.session.flush()

    snapshot = create_working_snapshot(
        project_ulid=project.ulid,
        actor_ulid=project.ulid,
        snapshot_label=f"{title} Basis",
        scope_summary=title,
    )
    add_budget_line(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=project.ulid,
        label="Initial cost",
        line_kind="materials",
        estimated_total_cents=25000,
    )
    locked = lock_snapshot(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=project.ulid,
    )
    db.session.flush()

    draft = create_draft_from_snapshot(
        project_ulid=project.ulid,
        snapshot_ulid=locked["ulid"],
        actor_ulid=project.ulid,
        title=title,
        summary=f"{title} summary",
        scope_summary=title,
        requested_amount_cents=25000,
        spending_class_candidate=spending_class,
        source_profile_key=source_profile_key,
        tag_any=tag_any,
    )
    draft = mark_draft_ready_for_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    draft = submit_draft_for_governance_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    draft = approve_draft_for_publish(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
        governance_decision=governance_v2.GovernanceReviewDecisionDTO(
            decision="approved",
            governance_note="Governance semantics approved for publish.",
            approved_spending_class=spending_class,
            approved_source_profile_key=source_profile_key,
            eligible_fund_codes=tuple(eligible_fund_codes),
            default_restriction_keys=tuple(default_restriction_keys),
            approved_tag_any=tuple(
                part.strip()
                for part in str(tag_any or "").split(",")
                if part.strip()
            ),
            decision_fingerprint="fp-route-funding-match",
            validation_errors=(),
            reason_codes=(),
            matched_rule_ids=(),
        ),
    )
    promoted = promote_draft_to_funding_demand(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    db.session.flush()
    return promoted["funding_demand"]["funding_demand_ulid"]


def test_compute_opportunity_match_likely_fit(app):
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


def test_compute_opportunity_match_caution_and_manual_review(app):
    with app.app_context():
        demand_ulid = _create_published_demand(
            title="Caution Demand",
            spending_class="basic_needs",
            tag_any="welcome_home_kit",
            source_profile_key="mission_local_veterans_cash",
            default_restriction_keys=("local_only", "vet_only"),
            eligible_fund_codes=("general_unrestricted",),
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
            reason == "Restriction posture aligns with local-only scope."
            for reason in view.positive_reasons
        )
        assert any(
            reason == "Board review commonly required."
            for reason in view.caution_reasons
        )
        assert any(
            reason == "Prior decline history exists."
            for reason in view.caution_reasons
        )


def test_list_opportunity_matches_sorts_likely_before_caution(app):
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


def test_sponsor_opportunity_match_to_dto_shapes_output(app):
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
