# tests/slices/sponsors/test_sponsors_funding_context.py

from __future__ import annotations

from dataclasses import replace

from app.extensions import db
from app.extensions.contracts import (
    calendar_v2,
    finance_v2,
    governance_v2,
    sponsors_v2,
)
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
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.sponsors.mapper import workflow_to_intent_guidance
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_funding import (
    create_funding_intent,
    get_funding_opportunity,
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


def _create_published_demand() -> str:
    project = Project(
        project_title="Context Project",
        status="draft_planning",
        funding_profile_key="mission_local_veterans_cash",
    )
    db.session.add(project)
    db.session.flush()

    snapshot = create_working_snapshot(
        project_ulid=project.ulid,
        actor_ulid=project.ulid,
        snapshot_label="Context Basis",
        scope_summary="Initial move-in support.",
    )
    add_budget_line(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=project.ulid,
        label="Initial cost",
        line_kind="materials",
        estimated_total_cents=17500,
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
        title="Context Demand",
        summary="Context summary",
        scope_summary="Initial move-in support.",
        requested_amount_cents=17500,
        spending_class_candidate="basic_needs",
        source_profile_key="mission_local_veterans_cash",
        tag_any="welcome_home_kit,crm_seed",
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
            approved_spending_class="basic_needs",
            approved_source_profile_key="mission_local_veterans_cash",
            eligible_fund_codes=("general_unrestricted",),
            default_restriction_keys=("local_only", "vet_only"),
            approved_tag_any=("welcome_home_kit", "crm_seed"),
            decision_fingerprint="fp-sponsors-context",
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


def _patch_published_package(
    monkeypatch,
    *,
    source_profile_key: str,
    ops_support_planned: bool,
    default_restriction_keys: tuple[str, ...] = ("local_only", "vet_only"),
    reserve_on_receive_expected: bool | None = None,
    allowed_realization_modes: tuple[str, ...] | None = None,
    recommended_income_kind: str | None = None,
    bridge_support_possible: bool | None = None,
) -> None:
    real_pkg = calendar_v2.get_published_funding_demand_package

    if source_profile_key == "welcome_home_reimbursement_bridgeable":
        summary = governance_v2.FundingSourceProfileSummaryDTO(
            key=source_profile_key,
            source_kind="grant",
            support_mode="reimbursement",
            approval_posture="standard",
            default_restriction_keys=tuple(default_restriction_keys),
            bridge_allowed=True,
            repayment_expectation="reimbursement_expected",
            forgiveness_rule="not_applicable",
            auto_ops_bridge_on_publish=False,
        )
        reserve_on_receive_expected = (
            False
            if reserve_on_receive_expected is None
            else reserve_on_receive_expected
        )
        allowed_realization_modes = (
            ("pledge", "reimbursement_receipt")
            if allowed_realization_modes is None
            else allowed_realization_modes
        )
        recommended_income_kind = (
            "reimbursement"
            if recommended_income_kind is None
            else recommended_income_kind
        )
        bridge_support_possible = (
            True
            if bridge_support_possible is None
            else bridge_support_possible
        )
    else:
        summary = governance_v2.FundingSourceProfileSummaryDTO(
            key=source_profile_key,
            source_kind="cash",
            support_mode="direct_support",
            approval_posture="standard",
            default_restriction_keys=tuple(default_restriction_keys),
            bridge_allowed=False,
            repayment_expectation="none",
            forgiveness_rule="not_applicable",
            auto_ops_bridge_on_publish=False,
        )
        reserve_on_receive_expected = (
            True
            if reserve_on_receive_expected is None
            else reserve_on_receive_expected
        )
        allowed_realization_modes = (
            ("pledge", "donation")
            if allowed_realization_modes is None
            else allowed_realization_modes
        )
        recommended_income_kind = (
            "donation"
            if recommended_income_kind is None
            else recommended_income_kind
        )
        bridge_support_possible = (
            False
            if bridge_support_possible is None
            else bridge_support_possible
        )

    def fake_pkg(funding_demand_ulid: str):
        pkg = real_pkg(funding_demand_ulid)
        return replace(
            pkg,
            planning=replace(
                pkg.planning,
                source_profile_key=source_profile_key,
                ops_support_planned=ops_support_planned,
            ),
            policy=replace(
                pkg.policy,
                default_restriction_keys=tuple(default_restriction_keys),
                source_profile_summary=summary,
            ),
            workflow=replace(
                pkg.workflow,
                reserve_on_receive_expected=reserve_on_receive_expected,
                recommended_income_kind=recommended_income_kind,
                bridge_support_possible=bridge_support_possible,
                allowed_realization_modes=tuple(
                    allowed_realization_modes or ()
                ),
            ),
        )

    def fake_ctx(funding_demand_ulid: str):
        pkg = fake_pkg(funding_demand_ulid)
        return calendar_v2.FundingDemandContextDTO(
            schema_version=pkg.schema_version,
            demand=pkg.demand,
            planning=pkg.planning,
            policy=pkg.policy,
            workflow=pkg.workflow,
        )

    monkeypatch.setattr(
        calendar_v2,
        "get_published_funding_demand_package",
        fake_pkg,
    )
    monkeypatch.setattr(
        calendar_v2,
        "get_funding_demand_context",
        fake_ctx,
    )


def test_get_funding_opportunity_uses_context_packet(app, monkeypatch):
    _patch_published_package(
        monkeypatch,
        source_profile_key="mission_local_veterans_cash",
        ops_support_planned=False,
    )

    with app.app_context():
        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Context Sponsor")

        create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "pledge",
                "amount_cents": 9000,
                "status": "committed",
                "note": "crm context",
            },
            actor_ulid=None,
            request_id="req-intent-context",
        )
        db.session.flush()

        detail = get_funding_opportunity(demand_ulid)

        assert detail.planning.project_title == "Context Project"
        assert detail.planning.source_profile_key
        assert detail.workflow.allowed_realization_modes
        assert detail.policy.eligible_fund_codes
        assert detail.policy.decision_fingerprint
        assert detail.totals.pledged_cents == 9000
        assert detail.money.received_cents == 0
        assert detail.money.remaining_goal_cents == 17500
        assert detail.money.uncovered_pipeline_gap_cents == 8500


def test_realize_funding_intent_defaults_from_context(app, monkeypatch):
    _patch_published_package(
        monkeypatch,
        source_profile_key="mission_local_veterans_cash",
        ops_support_planned=False,
    )

    with app.app_context():
        ensure_default_accounts()
        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Default Sponsor")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "donation",
                "amount_cents": 17500,
                "status": "committed",
                "note": "default realization",
            },
            actor_ulid=None,
            request_id="req-intent-defaults",
        )
        db.session.flush()

        detail = get_funding_opportunity(demand_ulid)
        fund_code = detail.policy.eligible_fund_codes[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_code=fund_code,
                receipt_method="bank",
                request_id="req-realize-defaults",
            )
        )
        db.session.flush()

        assert out.status == "fulfilled"


def test_realize_funding_intent_skips_reserve_when_context_expects_false(
    app, monkeypatch
):
    _patch_published_package(
        monkeypatch,
        source_profile_key="welcome_home_reimbursement_bridgeable",
        ops_support_planned=False,
        reserve_on_receive_expected=False,
        allowed_realization_modes=("pledge", "reimbursement_receipt"),
    )

    with app.app_context():
        ensure_default_accounts()
        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("No Reserve Sponsor")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "pledge",
                "amount_cents": 17500,
                "status": "committed",
                "note": "no reserve expected",
            },
            actor_ulid=None,
            request_id="req-intent-no-reserve",
        )
        db.session.flush()

        detail = get_funding_opportunity(demand_ulid)
        assert detail.workflow.reserve_on_receive_expected is False
        fund_code = detail.policy.eligible_fund_codes[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_code=fund_code,
                receipt_method="bank",
                request_id="req-realize-no-reserve",
            )
        )
        db.session.flush()

        assert out.status == "fulfilled"
        assert out.reserve_ulid is None


def test_realize_funding_intent_explicit_reserve_override_wins(
    app, monkeypatch
):
    _patch_published_package(
        monkeypatch,
        source_profile_key="welcome_home_reimbursement_bridgeable",
        ops_support_planned=False,
        reserve_on_receive_expected=False,
        allowed_realization_modes=("pledge", "reimbursement_receipt"),
    )

    with app.app_context():
        ensure_default_accounts()
        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Reserve Override Sponsor")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "pledge",
                "amount_cents": 17500,
                "status": "committed",
                "note": "force reserve",
            },
            actor_ulid=None,
            request_id="req-intent-force-reserve",
        )
        db.session.flush()

        detail = get_funding_opportunity(demand_ulid)
        assert detail.workflow.reserve_on_receive_expected is False
        fund_code = detail.policy.eligible_fund_codes[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_code=fund_code,
                receipt_method="bank",
                reserve_on_receive=True,
                request_id="req-realize-force-reserve",
            )
        )
        db.session.flush()

        assert out.status == "fulfilled"
        assert out.reserve_ulid


def test_realize_funding_intent_merges_context_and_fund_defaults(
    app, monkeypatch
):
    _patch_published_package(
        monkeypatch,
        source_profile_key="mission_local_veterans_cash",
        ops_support_planned=False,
        default_restriction_keys=("local_only", "vet_only"),
    )

    captured: dict[str, object] = {}

    def fake_apply_fund_defaults(*, fund_code: str, restriction_keys):
        captured["apply_in"] = tuple(restriction_keys or ())
        return ("temporarily_restricted",)

    def fake_validate_semantic_keys(**kwargs):
        captured["validate_restriction_keys"] = tuple(
            kwargs.get("restriction_keys") or ()
        )
        return governance_v2.SemanticValidationResultDTO(
            ok=True,
            errors=(),
            unknown_keys=(),
        )

    def fake_preview(req):
        captured["preview_restriction_keys"] = tuple(
            req.restriction_keys or ()
        )
        return governance_v2.FundingDecisionDTO(
            allowed=True,
            eligible_fund_codes=(req.selected_fund_code or "",),
            selected_fund_code=req.selected_fund_code,
            required_approvals=(),
            reason_codes=(),
            matched_rule_ids=(),
            decision_fingerprint="fp-merged",
        )

    def fake_get_fund_code(fund_code: str):
        return governance_v2.FundKeyDTO(
            key=fund_code,
            label="Test Fund",
            archetype="temporarily_restricted",
            default_restriction_keys=("temporarily_restricted",),
        )

    def fake_post_income(req):
        captured["posted_income_kind"] = req.income_kind
        return finance_v2.PostedDTO(
            id="journal-test",
            amount_cents=req.amount_cents,
            flags=(),
        )

    def fake_reserve_funds(req):
        return finance_v2.PostedDTO(
            id="reserve-test",
            amount_cents=req.amount_cents,
            flags=("reserved",),
        )

    with app.app_context():
        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Merged Restriction Sponsor")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "donation",
                "amount_cents": 17500,
                "status": "committed",
                "note": "restriction merge",
            },
            actor_ulid=None,
            request_id="req-intent-merge",
        )
        db.session.flush()

        detail = get_funding_opportunity(demand_ulid)
        fund_code = detail.policy.eligible_fund_codes[0]

        monkeypatch.setattr(
            governance_v2, "apply_fund_defaults", fake_apply_fund_defaults
        )
        monkeypatch.setattr(
            governance_v2,
            "validate_semantic_keys",
            fake_validate_semantic_keys,
        )
        monkeypatch.setattr(
            governance_v2, "preview_funding_decision", fake_preview
        )
        monkeypatch.setattr(
            governance_v2, "get_fund_code", fake_get_fund_code
        )
        monkeypatch.setattr(finance_v2, "post_income", fake_post_income)
        monkeypatch.setattr(finance_v2, "reserve_funds", fake_reserve_funds)

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_code=fund_code,
                receipt_method="bank",
                request_id="req-realize-merge",
            )
        )
        db.session.flush()

        merged = set(captured["validate_restriction_keys"])
        assert captured["apply_in"] == ("local_only", "vet_only")
        assert {"local_only", "vet_only", "temporarily_restricted"} <= merged
        assert set(captured["preview_restriction_keys"]) == merged
        assert out.reserve_ulid == "reserve-test"


def test_workflow_to_intent_guidance_is_advisory() -> None:
    guidance = workflow_to_intent_guidance(
        ("pledge", "reimbursement_receipt")
    )

    assert guidance.suggested_intent_kinds == ("pledge",)
    by_kind = {row.intent_kind: row for row in guidance.advisory}

    assert by_kind["pledge"].advised is True
    assert by_kind["donation"].advised is False
    assert by_kind["pass_through"].advised is False
    assert "Sponsor-local" in by_kind["pass_through"].reason
