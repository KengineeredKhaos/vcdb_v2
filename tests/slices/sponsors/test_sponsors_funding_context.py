# tests/slices/sponsors/test_sponsors_funding_context.py

from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import finance_v2, governance_v2, sponsors_v2
from app.slices.calendar.models import Project
from app.slices.calendar.services_funding import (
    create_funding_demand,
    publish_funding_demand,
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
        status="planned",
    )
    db.session.add(project)
    db.session.flush()

    row = create_funding_demand(
        {
            "project_ulid": project.ulid,
            "title": "Context Demand",
            "goal_cents": 17500,
            "deadline_date": "2026-04-10",
            "spending_class": "basic_needs",
            "tag_any": "welcome_home_kit,crm_seed",
        },
        actor_ulid=None,
        request_id="req-context-create",
    )
    db.session.flush()

    row = publish_funding_demand(
        row.ulid,
        actor_ulid=None,
        request_id="req-context-publish",
    )
    db.session.flush()
    return row.ulid


def test_get_funding_opportunity_uses_context_packet(app, monkeypatch):
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
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
        assert detail.policy.eligible_fund_keys
        assert detail.totals.pledged_cents == 9000
        assert detail.money.received_cents == 0
        assert detail.money.remaining_goal_cents == 17500
        assert detail.money.uncovered_pipeline_gap_cents == 8500


def test_realize_funding_intent_defaults_from_context(app, monkeypatch):
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
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
        fund_key = detail.policy.eligible_fund_keys[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_key=fund_key,
                receipt_method="bank",
                request_id="req-realize-defaults",
            )
        )
        db.session.flush()

        assert out.status == "fulfilled"


def test_realize_funding_intent_skips_reserve_when_context_expects_false(
    app, monkeypatch
):
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key="welcome_home_reimbursement_bridgeable",
            ops_support_planned=False,
        ),
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
        fund_key = detail.policy.eligible_fund_keys[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_key=fund_key,
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
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key="welcome_home_reimbursement_bridgeable",
            ops_support_planned=False,
        ),
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
        fund_key = detail.policy.eligible_fund_keys[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_key=fund_key,
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
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    captured: dict[str, object] = {}

    def fake_apply_fund_defaults(*, fund_key: str, restriction_keys):
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
            eligible_fund_keys=(req.selected_fund_key or "",),
            selected_fund_key=req.selected_fund_key,
            required_approvals=(),
            reason_codes=(),
            matched_rule_ids=(),
            decision_fingerprint="fp-merged",
        )

    def fake_get_fund_key(fund_key: str):
        return governance_v2.FundKeyDTO(
            key=fund_key,
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
        fund_key = detail.policy.eligible_fund_keys[0]

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
        monkeypatch.setattr(governance_v2, "get_fund_key", fake_get_fund_key)
        monkeypatch.setattr(finance_v2, "post_income", fake_post_income)
        monkeypatch.setattr(finance_v2, "reserve_funds", fake_reserve_funds)

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_key=fund_key,
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
