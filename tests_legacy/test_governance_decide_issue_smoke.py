# tests/test_governance_decide_issue_smoke.py
import types

import pytest

from app.extensions.contracts.customer_v2 import CustomerEligibilitySnapshot
from app.extensions.contracts.governance_v2 import (
    RestrictionContext,
    decide_issue,
)


@pytest.fixture(autouse=True)
def stub_external(monkeypatch):
    # calendar: no blackout
    import app.extensions.contracts.calendar_v2 as calendar_v2

    monkeypatch.setattr(
        calendar_v2, "is_blackout", lambda project_ulid, when_iso: False
    )

    # catalog: provide a tiny active list
    class SKUObj:
        def __init__(self, code, ck, cost):
            self.code = code
            self.classification_key = ck
            self.default_cost_cents = cost
            self.active = True

    import app.extensions.contracts.catalog_v2 as catalog_v2

    monkeypatch.setattr(
        catalog_v2,
        "list_skus",
        lambda active_only=True: [
            SKUObj("UG-TP-DR-M-OD-V-001", "basic_needs.clothing.top", 0),
            SKUObj("HS-SL-DR-*-*-U-001", "housing.sleeping_gear.bag", 0),
        ],
    )

    # cadence: none issued recently
    import app.extensions.contracts.logistics_v2 as logistics_v2

    monkeypatch.setattr(
        logistics_v2,
        "count_issues_in_window",
        lambda customer_ulid, ck, days, as_of_iso: 0,
    )


def test_veteran_only_top_allows_for_verified_vet(app_ctx, db_session):
    # Assume your policy has a veteran-only rule for clothing.top
    snap = CustomerEligibilitySnapshot(
        customer_ulid="01HFAKEVETVETVETVETVETVETV",
        is_veteran_verified=True,
        is_homeless_verified=False,
        tier1_min=2,
        tier2_min=None,
        tier3_min=None,
        as_of_iso="2025-10-25T00:00:00.000Z",
    )
    # Monkeypatch provider so test is self-contained
    import app.extensions.contracts.customer_v2 as customer_v2

    customer_v2.get_eligibility_snapshot = lambda _: snap

    ctx = RestrictionContext(
        customer_ulid=snap.customer_ulid,
        sku_code="UG-TP-DR-M-OD-V-0F7",
        classification_key="basic_needs.clothing.top",
        cost_cents=0,
        as_of_iso="2025-10-25T00:00:00.000Z",
        project_ulid=None,
    )
    d = decide_issue(ctx)
    assert d.allowed is True
    assert d.approver_required is None


def test_veteran_only_top_denies_for_non_vet(app_ctx, db_session):
    import app.extensions.contracts.customer_v2 as customer_v2
    from app.extensions.contracts.customer_v2 import (
        CustomerEligibilitySnapshot,
    )

    snap = CustomerEligibilitySnapshot(
        customer_ulid="01HFNONVETERAN___________",
        is_veteran_verified=False,
        is_homeless_verified=False,
        tier1_min=2,
        tier2_min=None,
        tier3_min=None,
        as_of_iso="2025-10-25T00:00:00.000Z",
    )
    customer_v2.get_eligibility_snapshot = lambda _: snap

    from app.extensions.contracts.governance_v2 import (
        RestrictionContext,
        decide_issue,
    )

    ctx = RestrictionContext(
        customer_ulid=snap.customer_ulid,
        sku_code="UG-TP-DR-M-OD-V-0F7",
        classification_key="basic_needs.clothing.top",
        cost_cents=0,
        as_of_iso="2025-10-25T00:00:00.000Z",
        project_ulid=None,
    )
    d = decide_issue(ctx)
    assert d.allowed is False
    assert (
        d.reason in {"cadence_exceeded", "blackout", None}
        or d.reason == "qualifier_failed"
    )
