# tests/test_customer_contract.py
import pytest

from app.extensions import db
from app.lib.ids import new_ulid
from app.extensions.contracts import customers_v2 as contract
from app.slices.entity import services as ent_svc
from app.slices.customers import services as cust_svc
from app.slices.customers.models import CustomerEligibility, CustomerHistory


def _mk_person_ulid():
    return ent_svc.ensure_person(
        first_name="Demo",
        last_name="Customer",
        email=None,
        phone=None,
        request_id=new_ulid(),
        actor_ulid=None,
    )


def _mk_customer_ulid() -> str:
    ent_ulid = _mk_person_ulid()
    return cust_svc.ensure_customer(
        entity_ulid=ent_ulid,
        request_id=new_ulid(),
        actor_ulid=None,
    )


def test_get_needs_profile_defaults(app):
    cust_ulid = _mk_customer_ulid()

    prof = contract.get_needs_profile(cust_ulid)
    assert prof.customer_ulid == cust_ulid
    # defaults before any updates
    assert prof.is_veteran_verified is False
    assert prof.is_homeless_verified is False
    assert prof.tier1_min is None
    assert prof.tier2_min is None
    assert prof.tier3_min is None
    assert isinstance(prof.as_of_iso, str)


def test_update_tier1_sets_homeless_flag_and_history(app):
    cust_ulid = _mk_customer_ulid()

    # Tier-1 with housing=1 (immediate) → homeless=True
    r = contract.update_tier1(
        customer_ulid=cust_ulid,
        payload={
            "food": 2,
            "hygiene": 2,
            "health": 2,
            "housing": 1,
            "clothing": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    assert r.customer_ulid == cust_ulid
    assert r.section == "profile:needs:tier1"
    assert isinstance(r.version_ptr, str)

    # Eligibility snapshot reflects the derived flags/min
    snap = cust_svc.get_eligibility_snapshot(cust_ulid)
    assert snap.is_homeless_verified is True
    assert snap.tier1_min == 1

    # History row was written and matches the version_ptr
    hist = db.session.get(CustomerHistory, r.version_ptr)
    assert hist is not None
    assert hist.customer_ulid == cust_ulid
    assert hist.section == "profile:needs:tier1"


def test_verify_veteran_other_requires_governor(app):
    cust_ulid = _mk_customer_ulid()

    # Attempt with 'other' without governor → PermissionDenied
    with pytest.raises(contract.PermissionDenied):
        contract.verify_veteran(
            customer_ulid=cust_ulid,
            method="other",
            verified=True,
            actor_ulid=None,
            actor_has_governor=False,
            request_id=new_ulid(),
        )

    # Now succeed with governor
    res = contract.verify_veteran(
        customer_ulid=cust_ulid,
        method="other",
        verified=True,
        actor_ulid="01TESTGOVERNORULID000000000000",
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    assert res.customer_ulid == cust_ulid
    assert res.is_veteran_verified is True
    assert res.veteran_method in (
        None,
        "other",
    )  # method may be surfaced via dashboard


def test_update_tier2_watchlist_and_dashboard(app):
    cust_ulid = _mk_customer_ulid()

    # Put tier1 to non-crisis to isolate tier2 behavior
    contract.update_tier1(
        customer_ulid=cust_ulid,
        payload={
            "food": 2,
            "hygiene": 2,
            "health": 2,
            "housing": 2,
            "clothing": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )

    # Tier-2 with income=1 should flip watchlist=True and tier2_min=1
    contract.update_tier2(
        customer_ulid=cust_ulid,
        payload={
            "income": 1,
            "employment": 2,
            "transportation": 3,
            "education": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )

    dv = contract.get_dashboard_view(cust_ulid)
    assert dv is not None
    assert dv.customer_ulid == cust_ulid
    assert dv.tier2_min == 1
    assert dv.watchlist is True
    assert "income" in dv.tier_factors["tier2"]

    # Needs profile matches coarse mins/flags
    prof = contract.get_needs_profile(cust_ulid)
    assert prof.tier2_min == 1
    assert isinstance(prof.as_of_iso, str)


def test_verify_veteran_basic_methods_set_flag(app):
    cust_ulid = _mk_customer_ulid()

    # verify via VA ID (no governor needed)
    res = contract.verify_veteran(
        customer_ulid=cust_ulid,
        method="va_id",
        verified=True,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    assert res.is_veteran_verified is True

    # eligibility row persisted
    elig = (
        db.session.query(CustomerEligibility)
        .filter_by(customer_ulid=cust_ulid)
        .one()
    )
    assert elig.is_veteran_verified is True
