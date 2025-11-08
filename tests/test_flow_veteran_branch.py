# tests/test_flow_veteran_branch.py
import contextlib
import pytest
from conftest import with_readonly_session
from tests._ulid import assert_ulid, make_ulid
from app.extensions.contracts import (
    customers_v2,
    resources_v2,
    sponsors_v2,
    governance_v2,
    logistics_v2,
    calendar_v2,
)

pytestmark = pytest.mark.flow  # run with: pytest -q -m flow

# This flow covers:
#   Eligibility → Resource Match → Allocation Preview → Draw Preview (GET-only)

def _expect_keys(obj: dict, keys: set[str]):
    missing = keys - set(obj.keys())
    assert not missing, f"Missing keys: {sorted(missing)}"

    # Pure GETs under isolated read-only session
    with with_readonly_session():
        prof   = customers_v2.get_profile(customer_ulid=cust_ulid)
        rprof  = resources_v2.get_profile(resource_ulid=res_ulid)
        limits = governance_v2.get_spending_limits()
        pol    = sponsors_v2.get_policy(sponsor_ulid=spon_ulid)
        gate   = logistics_v2.get_sku_cadence(customer_ulid=cust_ulid, sku="AC-GL-LC-L-LB-U-00B")
        blk    = calendar_v2.blackout_ok(when_iso=None)

        # quick shape sanity
        _expect_keys(prof,   {"customer_ulid", "flags", "tier1"})
        _expect_keys(rprof,  {"resource_ulid", "status", "capabilities"})
        _expect_keys(limits, {"staff_limit_cents"})
        _expect_keys(pol,    {"sponsor_ulid", "caps", "constraints"})
        _expect_keys(gate,   {"eligible", "next_eligible_at_iso"})
        _expect_keys(blk,    {"ok", "reason"})

        # echo checks to catch ULID mixups
        assert prof["customer_ulid"] == cust_ulid
        assert rprof["resource_ulid"] == res_ulid
        assert pol["sponsor_ulid"]   == spon_ulid
