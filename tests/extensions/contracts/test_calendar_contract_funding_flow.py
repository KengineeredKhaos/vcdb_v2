# tests/extensions/contracts/calendar_v2_funding_flow.py

from __future__ import annotations

import pytest

from app.extensions.contracts import calendar_v2
from app.extensions.errors import ContractError


def test_encumber_project_funds_rejects_blank_fund_code():
    req = calendar_v2.ProjectEncumbranceRequestDTO(
        funding_demand_ulid="01TESTTESTTESTTESTTESTTEST",
        amount_cents=1000,
        fund_code="",
        expense_kind="event_expense",
        happened_at_utc="2026-03-20T12:00:00Z",
    )
    with pytest.raises(ContractError) as exc:
        calendar_v2.encumber_project_funds(req)
    assert exc.value.code == "bad_argument"


def test_allocate_ops_float_rejects_zero_amount():
    req = calendar_v2.OpsFloatAllocationRequestDTO(
        source_funding_demand_ulid="01TESTTESTTESTTESTTESTTEST",
        dest_funding_demand_ulid="01TESTTESTTESTTESTTESTTST1",
        fund_code="general_unrestricted",
        amount_cents=0,
        support_mode="seed",
    )
    with pytest.raises(ContractError) as exc:
        calendar_v2.allocate_ops_float_to_project(req)
    assert exc.value.code == "bad_argument"


def test_spend_project_funds_rejects_bad_payee_ulid():
    req = calendar_v2.ProjectSpendRequestDTO(
        encumbrance_ulid="01TESTTESTTESTTESTTESTTEST",
        amount_cents=1000,
        expense_kind="event_expense",
        payment_method="cash",
        happened_at_utc="2026-03-20T12:00:00Z",
        payee_entity_ulid="not-a-ulid",
    )
    with pytest.raises(ContractError) as exc:
        calendar_v2.spend_project_funds(req)
    assert exc.value.code == "bad_argument"
