# tests/extensions/contracts/test_governance_funding_decisions.py

from __future__ import annotations

from app.extensions.contracts import governance_v2


def test_finance_taxonomy_contract_returns_values():
    tx = governance_v2.get_finance_taxonomy()

    assert tx.fund_keys
    assert tx.restriction_keys
    assert tx.income_kinds
    assert tx.expense_kinds
    assert tx.spending_classes


def test_preview_funding_decision_uses_source_profile_selectors():
    req = governance_v2.FundingDecisionRequestDTO(
        op="encumber",
        amount_cents=5000,
        funding_demand_ulid="01TESTFUNDINGDEMAND00000001",
        project_ulid="01TESTPROJECT00000000000001",
        spending_class="basic_needs",
        source_profile_key="welcome_home_reimbursement_bridgeable",
        restriction_keys=(),
        demand_eligible_fund_keys=(),
        tag_any=("welcome_home_kit",),
        selected_fund_key=None,
        actor_rbac_roles=(),
        actor_domain_roles=(),
    )

    out = governance_v2.preview_funding_decision(req)

    assert out.allowed is True
    assert out.eligible_fund_keys
    assert out.eligible_fund_keys[0] == "welcome_home_reimbursement"
    assert out.decision_fingerprint


def test_preview_funding_decision_fingerprint_is_stable():
    req = governance_v2.FundingDecisionRequestDTO(
        op="encumber",
        amount_cents=5000,
        funding_demand_ulid="01TESTFUNDINGDEMAND00000002",
        project_ulid="01TESTPROJECT00000000000002",
        spending_class="admin",
        income_kind=None,
        expense_kind=None,
        restriction_keys=(),
        demand_eligible_fund_keys=(),
        tag_any=(),
        selected_fund_key=None,
        actor_rbac_roles=(),
        actor_domain_roles=(),
    )

    a = governance_v2.preview_funding_decision(req)
    b = governance_v2.preview_funding_decision(req)

    assert a.decision_fingerprint == b.decision_fingerprint


def test_preview_ops_float_seed_requires_governor():
    req = governance_v2.OpsFloatDecisionRequestDTO(
        support_mode="seed",
        amount_cents=5000,
        fund_key="general_unrestricted",
        source_funding_demand_ulid="01TESTOPSDEMAND00000000000001",
        source_project_ulid="01TESTOPSPROJ00000000000001",
        dest_funding_demand_ulid="01TESTPROJDEMAND000000000001",
        dest_project_ulid="01TESTPROJ000000000000000001",
        action="allocate",
        actor_domain_roles=(),
    )

    out = governance_v2.preview_ops_float(req)

    assert out.allowed is True
    assert "governor" in out.required_approvals
    assert out.selected_fund_key == "general_unrestricted"


def test_preview_ops_float_bridge_is_auto_allowed():
    req = governance_v2.OpsFloatDecisionRequestDTO(
        support_mode="bridge",
        amount_cents=3000,
        fund_key="general_unrestricted",
        source_funding_demand_ulid="01TESTOPSDEMAND00000000000002",
        source_project_ulid="01TESTOPSPROJ00000000000002",
        dest_funding_demand_ulid="01TESTPROJDEMAND000000000002",
        dest_project_ulid="01TESTPROJ000000000000000002",
        action="allocate",
        actor_domain_roles=(),
    )

    out = governance_v2.preview_ops_float(req)

    assert out.allowed is True
    assert out.required_approvals == ()
    assert "ops_float_auto_allowed" in out.reason_codes
