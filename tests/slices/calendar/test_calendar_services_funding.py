from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.contracts import governance_v2
from app.extensions.contracts.calendar_v2 import (
    get_published_funding_demand_package,
)
from app.slices.calendar.models import FundingDemand, Project
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
from app.slices.calendar.services_funding import (
    get_funding_demand,
    get_funding_demand_context,
    get_funding_demand_view,
    get_spending_class_choices,
    list_published_funding_demands,
)


def _make_project(*, title: str = "Funding Services Project") -> Project:
    row = Project(
        project_title=title,
        status="draft_planning",
        funding_profile_key="ops_bridge_preapproved",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _create_published_demand(
    *, title: str = "Welcome Home Ask", amount_cents: int = 12000
):
    project = _make_project(title="Published Demand Project")
    actor_ulid = project.ulid

    snapshot = create_working_snapshot(
        project_ulid=project.ulid,
        actor_ulid=actor_ulid,
        snapshot_label="Working Budget",
        scope_summary="Full project scope",
    )
    add_budget_line(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=actor_ulid,
        label="Estimated project cost",
        line_kind="materials",
        estimated_total_cents=amount_cents,
    )
    snapshot = lock_snapshot(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=actor_ulid,
    )

    draft = create_draft_from_snapshot(
        project_ulid=project.ulid,
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=actor_ulid,
        title=title,
        summary=title,
        scope_summary="Full project scope",
        requested_amount_cents=amount_cents,
        spending_class_candidate="basic_needs",
        source_profile_key="ops_bridge_preapproved",
        tag_any="welcome_home_kit",
    )
    draft = mark_draft_ready_for_review(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
    )
    draft = submit_draft_for_governance_review(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
    )
    draft = approve_draft_for_publish(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
        governance_decision=governance_v2.GovernanceReviewDecisionDTO(
            decision="approved",
            governance_note="Governance semantics approved for publish.",
            approved_spending_class="basic_needs",
            approved_source_profile_key="ops_bridge_preapproved",
            eligible_fund_codes=("general_unrestricted",),
            default_restriction_keys=(),
            approved_tag_any=("welcome_home_kit",),
            decision_fingerprint="fp-test-calendar-funding",
            validation_errors=(),
            reason_codes=("source_profile:test",),
            matched_rule_ids=("selector:test",),
        ),
    )
    promoted = promote_draft_to_funding_demand(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
    )
    db.session.flush()
    return {
        "project": project,
        "snapshot": snapshot,
        "draft": draft,
        "funding": promoted["funding_demand"],
    }


def test_get_spending_class_choices_includes_select_and_real_values(app):
    with app.app_context():
        choices = get_spending_class_choices()

    assert choices
    assert choices[0] == ("", "— Select —")
    keys = {key for key, _label in choices[1:]}
    assert "basic_needs" in keys


def test_get_funding_demand_context_returns_snapshot_from_new_pipeline(app):
    with app.app_context():
        built = _create_published_demand(amount_cents=12000)
        project = built["project"]
        snapshot = built["snapshot"]
        funding = built["funding"]
        funding_ulid = funding["funding_demand_ulid"]
        package = get_published_funding_demand_package(funding_ulid)

        payload = get_funding_demand_context(funding_ulid)
        dto = get_funding_demand(funding_ulid)
        view = get_funding_demand_view(funding_ulid)

        assert payload["schema_version"] == 2
        assert (
            payload["origin"]["demand_draft_ulid"] == built["draft"]["ulid"]
        )
        assert payload["origin"]["budget_snapshot_ulid"] == snapshot["ulid"]
        assert payload["origin"]["project_ulid"] == project.ulid

        assert (
            payload["planning"]["source_profile_key"]
            == "ops_bridge_preapproved"
        )
        assert payload["planning"]["scope_summary"] == "Full project scope"
        assert payload["policy"]["eligible_fund_codes"] == [
            "general_unrestricted"
        ]

        assert dto["funding_demand_ulid"] == funding_ulid
        assert dto["project_ulid"] == project.ulid
        assert dto["goal_cents"] == 12000
        assert view.funding_demand_ulid == funding_ulid
        assert view.status == "published"
        assert view.project_ulid == project.ulid
        assert view.goal_cents == 12000
        assert package.schema_version == 1
        assert package.origin.demand_draft_ulid == built["draft"]["ulid"]
        assert package.origin.budget_snapshot_ulid == snapshot["ulid"]
        assert package.origin.project_ulid == project.ulid
        assert package.demand.funding_demand_ulid == funding_ulid
        assert package.demand.project_ulid == project.ulid
        assert package.planning.source_profile_key == "ops_bridge_preapproved"
        assert package.policy.decision_fingerprint
        assert package.policy.eligible_fund_codes == ("general_unrestricted",)
        assert package.workflow.allowed_realization_modes


def test_list_published_funding_demands_filters_to_project_and_published(app):
    with app.app_context():
        built = _create_published_demand(
            title="Published One",
            amount_cents=8000,
        )
        project = built["project"]
        funding = built["funding"]
        funding_ulid = funding["funding_demand_ulid"]

        other_published = _create_published_demand(
            title="Published Other",
            amount_cents=9000,
        )
        other_project = other_published["project"]
        other_funding = other_published["funding"]

        draft_only_snapshot = create_working_snapshot(
            project_ulid=other_project.ulid,
            actor_ulid=other_project.ulid,
            snapshot_label="Other Working Budget",
            scope_summary="Other scope",
        )
        add_budget_line(
            snapshot_ulid=draft_only_snapshot["ulid"],
            actor_ulid=other_project.ulid,
            label="Other line",
            line_kind="materials",
            estimated_total_cents=5000,
        )
        lock_snapshot(
            snapshot_ulid=draft_only_snapshot["ulid"],
            actor_ulid=other_project.ulid,
        )
        draft_only = create_draft_from_snapshot(
            project_ulid=other_project.ulid,
            snapshot_ulid=draft_only_snapshot["ulid"],
            actor_ulid=other_project.ulid,
            title="Draft Only",
            requested_amount_cents=5000,
            spending_class_candidate="basic_needs",
            source_profile_key="ops_bridge_preapproved",
        )
        draft_ulid = draft_only["ulid"]

        rows = list_published_funding_demands(project_ulid=project.ulid)
        ulids = {row.funding_demand_ulid for row in rows}

        assert funding_ulid in ulids
        assert other_funding["funding_demand_ulid"] not in ulids
        assert draft_ulid not in ulids

        assert all(row.project_ulid == project.ulid for row in rows)


def test_get_funding_demand_context_raises_when_context_missing(app):
    with app.app_context():
        built = _create_published_demand()
        funding_ulid = built["funding"]["funding_demand_ulid"]
        row = db.session.get(FundingDemand, funding_ulid)
        assert row is not None
        row.published_context_json = None
        db.session.flush()

        with pytest.raises(ValueError, match="has no published context"):
            get_funding_demand_context(funding_ulid)
