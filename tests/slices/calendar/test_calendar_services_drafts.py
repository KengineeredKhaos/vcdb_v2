from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.extensions import db
from app.slices.calendar.models import DemandDraft, FundingDemand, Project
from app.slices.calendar.services_budget import (
    add_budget_line,
    create_working_snapshot,
    lock_snapshot,
)
from app.slices.calendar.services_drafts import (
    approve_draft_for_publish,
    create_draft_from_snapshot,
    demand_draft_view,
    mark_draft_ready_for_review,
    promote_draft_to_funding_demand,
    return_draft_for_revision,
    submit_draft_for_governance_review,
    update_draft,
)


def _patch_governance_ok(monkeypatch):
    from app.extensions.contracts import governance_v2
    from app.slices.calendar import services_drafts as svc

    monkeypatch.setattr(
        svc.gov,
        "validate_semantic_keys",
        lambda **kwargs: SimpleNamespace(ok=True, errors=[]),
    )
    monkeypatch.setattr(
        svc.gov,
        "get_funding_source_profile_summary",
        lambda key: governance_v2.FundingSourceProfileSummaryDTO(
            key=key,
            source_kind="grant",
            support_mode="reimbursement",
            approval_posture="standard",
            default_restriction_keys=("local_only",),
            bridge_allowed=False,
            repayment_expectation="none",
            forgiveness_rule="not_applicable",
            auto_ops_bridge_on_publish=False,
        ),
    )
    monkeypatch.setattr(
        svc.gov,
        "review_calendar_demand",
        lambda req: governance_v2.GovernanceReviewDecisionDTO(
            decision="approved",
            governance_note="Governance semantics approved for publish.",
            approved_spending_class=req.spending_class_candidate,
            approved_source_profile_key=req.source_profile_key_candidate,
            eligible_fund_codes=("general_unrestricted",),
            default_restriction_keys=("local_only",),
            approved_tag_any=tuple(req.tag_any or ()),
            decision_fingerprint="fp-draft-review",
            validation_errors=(),
            reason_codes=("source_profile:test",),
            matched_rule_ids=("selector:test",),
        ),
    )


def _make_project(*, title: str = "Draft Test Project") -> Project:
    row = Project(
        project_title=title,
        status="draft_planning",
        funding_profile_key="ops_bridge_preapproved",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _make_locked_snapshot(project_ulid: str, actor_ulid: str) -> dict:
    snapshot = create_working_snapshot(
        project_ulid=project_ulid,
        actor_ulid=actor_ulid,
        snapshot_label="Draft Basis",
        scope_summary="Phase 1",
    )
    add_budget_line(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=actor_ulid,
        label="Initial cost",
        line_kind="materials",
        estimated_total_cents=12000,
    )
    locked = lock_snapshot(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=actor_ulid,
    )
    db.session.flush()
    return locked


def test_create_draft_from_snapshot_requires_locked_budget_snapshot(
    app,
    ulid,
    monkeypatch,
):
    _patch_governance_ok(monkeypatch)

    with app.app_context():
        project = _make_project(title="Unlocked Snapshot Project")
        snapshot = create_working_snapshot(
            project_ulid=project.ulid,
            actor_ulid=ulid(),
            snapshot_label="Unlocked",
        )

        with pytest.raises(RuntimeError):
            create_draft_from_snapshot(
                project_ulid=project.ulid,
                snapshot_ulid=snapshot["ulid"],
                actor_ulid=ulid(),
                title="Should fail",
            )


def test_create_draft_defaults_amount_and_source_profile_from_project(
    app,
    ulid,
    monkeypatch,
):
    _patch_governance_ok(monkeypatch)

    with app.app_context():
        actor_ulid = ulid()
        project = _make_project(title="Defaulted Draft Project")
        snapshot = _make_locked_snapshot(project.ulid, actor_ulid)

        out = create_draft_from_snapshot(
            project_ulid=project.ulid,
            snapshot_ulid=snapshot["ulid"],
            actor_ulid=actor_ulid,
            title="Welcome Home Ask",
            tag_any="housing, housing, kit",
        )
        db.session.flush()

        assert out["status"] == "draft"
        assert out["requested_amount_cents"] == 12000
        assert out["source_profile_key"] == "ops_bridge_preapproved"
        assert out["tag_any"] == ["housing", "kit"]
        assert out["budget_snapshot_ulid"] == snapshot["ulid"]


def test_draft_review_lifecycle_return_update_approve_and_promote(
    app,
    ulid,
    monkeypatch,
):
    _patch_governance_ok(monkeypatch)

    with app.app_context():
        actor_ulid = ulid()
        project = _make_project(title="Lifecycle Project")
        snapshot = _make_locked_snapshot(project.ulid, actor_ulid)

        draft = create_draft_from_snapshot(
            project_ulid=project.ulid,
            snapshot_ulid=snapshot["ulid"],
            actor_ulid=actor_ulid,
            title="Original Ask",
            summary="Initial version",
            spending_class_candidate="basic_needs",
            tag_any=["welcome_home_kit"],
        )
        draft = mark_draft_ready_for_review(
            draft_ulid=draft["ulid"],
            actor_ulid=actor_ulid,
        )
        assert draft["status"] == "ready_for_review"
        assert draft["ready_for_review_at_utc"] is not None

        draft = submit_draft_for_governance_review(
            draft_ulid=draft["ulid"],
            actor_ulid=actor_ulid,
        )
        assert draft["status"] == "governance_review_pending"

        draft = return_draft_for_revision(
            draft_ulid=draft["ulid"],
            actor_ulid=actor_ulid,
            note="Tighten the narrative and source posture.",
        )
        assert draft["status"] == "returned_for_revision"
        assert draft["governance_note"] == (
            "Tighten the narrative and source posture."
        )
        assert draft["review_decided_at_utc"] is not None

        draft = update_draft(
            draft_ulid=draft["ulid"],
            actor_ulid=actor_ulid,
            title="Revised Ask",
            summary="Revised version",
            source_profile_key="restricted_project_grant_return_unused",
            tag_any=["welcome_home_kit", "furniture"],
        )
        assert draft["title"] == "Revised Ask"
        assert draft["source_profile_key"] == (
            "restricted_project_grant_return_unused"
        )
        assert draft["tag_any"] == ["welcome_home_kit", "furniture"]

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
            review_overrides={
                "spending_class_candidate": "basic_needs",
                "source_profile_key_candidate": (
                    "restricted_project_grant_return_unused"
                ),
                "tag_any": ["welcome_home_kit", "furniture"],
            },
        )
        assert draft["status"] == "approved_for_publish"
        assert draft["approved_for_publish_at_utc"] is not None
        assert draft["approved_semantics_json"]["decision"] == "approved"
        assert (
            draft["approved_semantics_json"]["approved_source_profile_key"]
            == "restricted_project_grant_return_unused"
        )
        assert draft["approved_semantics_json"]["eligible_fund_codes"] == [
            "general_unrestricted"
        ]
        assert (
            draft["approved_semantics_json"]["decision_fingerprint"]
            == "fp-draft-review"
        )

        promoted = promote_draft_to_funding_demand(
            draft_ulid=draft["ulid"],
            actor_ulid=actor_ulid,
        )
        db.session.flush()

        funding = promoted["funding_demand"]
        assert funding["status"] == "published"
        assert funding["goal_cents"] == 12000
        assert funding["eligible_fund_codes"] == ["general_unrestricted"]
        assert funding["published_at_utc"] is not None

        draft_row = db.session.get(DemandDraft, draft["ulid"])
        assert draft_row is not None
        assert draft_row.promoted_at_utc is not None

        funding_row = db.session.get(
            FundingDemand,
            funding["funding_demand_ulid"],
        )
        assert funding_row is not None
        assert funding_row.origin_draft_ulid == draft["ulid"]
        assert funding_row.project_ulid == project.ulid
        assert (
            funding_row.published_context_json["origin"]["demand_draft_ulid"]
            == draft["ulid"]
        )
        assert (
            funding_row.published_context_json["origin"][
                "budget_snapshot_ulid"
            ]
            == snapshot["ulid"]
        )


def test_promote_draft_to_funding_demand_rejects_second_promotion(
    app,
    ulid,
    monkeypatch,
):
    _patch_governance_ok(monkeypatch)

    with app.app_context():
        actor_ulid = ulid()
        project = _make_project(title="Promote Once Project")
        snapshot = _make_locked_snapshot(project.ulid, actor_ulid)

        draft = create_draft_from_snapshot(
            project_ulid=project.ulid,
            snapshot_ulid=snapshot["ulid"],
            actor_ulid=actor_ulid,
            title="Single Promotion Ask",
            spending_class_candidate="basic_needs",
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
            review_overrides={
                "spending_class_candidate": "basic_needs",
                "source_profile_key_candidate": (
                    "restricted_project_grant_return_unused"
                ),
                "tag_any": ["welcome_home_kit", "furniture"],
            },
        )
        promote_draft_to_funding_demand(
            draft_ulid=draft["ulid"],
            actor_ulid=actor_ulid,
        )
        db.session.flush()

        with pytest.raises(RuntimeError):
            promote_draft_to_funding_demand(
                draft_ulid=draft["ulid"],
                actor_ulid=actor_ulid,
            )
