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


def test_preview_funding_decision_returns_sane_result():
    req = governance_v2.FundingDecisionRequestDTO(
        op="encumber",
        amount_cents=5000,
        funding_demand_ulid="01TESTFUNDINGDEMAND00000001",
        project_ulid="01TESTPROJECT00000000000001",
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

    out = governance_v2.preview_funding_decision(req)

    assert isinstance(out.allowed, bool)
    assert isinstance(out.eligible_fund_keys, tuple)
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
