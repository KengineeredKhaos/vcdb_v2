# tests/test_customer_snapshot.py
from __future__ import annotations

import re

from app.extensions.contracts.customer_v2 import (
    CustomerEligibilitySnapshot,
    get_eligibility_snapshot,
)
from app.slices.customers.services import (
    set_tier_min,
    set_verification_flags,
)


def test_snapshot_default_creates_row(app_ctx, db_session):
    cust = "01HFZ7C5W8P6XQ8XW7WJH1M5ZQ"  # ULID-like placeholder
    snap = get_eligibility_snapshot(cust)
    assert isinstance(snap, CustomerEligibilitySnapshot)
    assert snap.customer_ulid == cust
    assert snap.is_veteran_verified is False
    assert snap.is_homeless_verified is False
    assert snap.tier1_min is None
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", snap.as_of_iso)


def test_snapshot_updates_flags_and_tiers(app_ctx, db_session):
    cust = "01HFZ7C5W8P6XQ8XW7WJH1M5ZR"
    set_verification_flags(cust, veteran=True)
    set_tier_min(cust, tier1=2)
    snap = get_eligibility_snapshot(cust)
    assert snap.is_veteran_verified is True
    assert snap.tier1_min == 2
