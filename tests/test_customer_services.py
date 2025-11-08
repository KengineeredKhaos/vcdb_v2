import json
import pytest

from app.extensions import db
from app.lib.ids import new_ulid
from app.lib.chrono import now_iso8601_ms
from app.slices.customers import services as cust_svc
from app.slices.customers.models import (
    Customer,
    CustomerEligibility,
    CustomerHistory,
)
from app.slices.entity import services as ent_svc
from app.slices.entity.models import (
    Entity,
)  # minimal insert; we avoid PII in tests

# --- simple helpers -----------------------------------------------------------


def _mk_entity() -> str:
    # Create a person entity via the service (sets kind='person', adds EntityPerson,
    # creates/updates primary contact if provided, and emits ledger).
    return ent_svc.ensure_person(
        first_name="Demo",
        last_name="Customer",
        email=None,
        phone=None,
        request_id=new_ulid(),
        actor_ulid=None,
    )


def _ensure_customer(entity_ulid):
    return cust_svc.ensure_customer(
        entity_ulid=entity_ulid, request_id=new_ulid(), actor_ulid=None
    )


# --- tests --------------------------------------------------------------------


def test_ensure_customer_idempotent(app):
    ent_ulid = _mk_entity()
    c1 = _ensure_customer(ent_ulid)
    c2 = _ensure_customer(ent_ulid)
    assert c1 == c2

    row = db.session.get(Customer, c1)
    assert row is not None
    assert row.entity_ulid == ent_ulid
    assert row.first_seen_utc is not None
    assert row.last_touch_utc is not None


def test_tier1_update_sets_flags_and_homelessness(app):
    ent_ulid = _mk_entity()
    cust_ulid = _ensure_customer(ent_ulid)

    # Tier-1: set housing=1 (immediate) → homeless flag True, flag_tier1_immediate True
    payload = {
        "food": 2,
        "hygiene": 2,
        "health": 2,
        "housing": 1,
        "clothing": 3,
    }
    vptr = cust_svc.update_tier1(
        customer_ulid=cust_ulid,
        payload=payload,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    assert isinstance(vptr, str)

    c = db.session.get(Customer, cust_ulid)
    assert c.flag_tier1_immediate is True
    assert c.flag_reason in (None, "housing=1") or "housing=1" in (
        c.flag_reason or ""
    )

    elig = (
        db.session.query(CustomerEligibility)
        .filter_by(customer_ulid=cust_ulid)
        .one()
    )
    assert elig.is_homeless_verified is True
    assert elig.tier1_min == 1
    assert elig.tier2_min is None
    assert elig.tier3_min is None

    # History row recorded for tier1
    h = (
        db.session.query(CustomerHistory)
        .filter_by(customer_ulid=cust_ulid, section="profile:needs:tier1")
        .order_by(CustomerHistory.version.desc())
        .first()
    )
    assert h is not None
    data = json.loads(h.data_json)
    assert data["housing"] == 1


def test_veteran_verification_basic_methods(app):
    ent_ulid = _mk_entity()
    cust_ulid = _ensure_customer(ent_ulid)

    # Set to verified via VA ID → allowed, no governor required
    snap = cust_svc.set_veteran_verification(
        customer_ulid=cust_ulid,
        method="va_id",
        verified=True,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    assert snap.is_veteran_verified is True

    # Clear it
    snap = cust_svc.set_veteran_verification(
        customer_ulid=cust_ulid,
        method="va_id",
        verified=False,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    assert snap.is_veteran_verified is False


def test_veteran_other_requires_governor(app):
    ent_ulid = _mk_entity()
    cust_ulid = _ensure_customer(ent_ulid)

    with pytest.raises(PermissionError):
        cust_svc.set_veteran_verification(
            customer_ulid=cust_ulid,
            method="other",
            verified=True,
            actor_ulid=None,
            actor_has_governor=False,  # should fail
            request_id=new_ulid(),
        )

    # Now succeed with governor
    snap = cust_svc.set_veteran_verification(
        customer_ulid=cust_ulid,
        method="other",
        verified=True,
        actor_ulid="01TESTGOVERNORULID000000000000",  # audit only
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    assert snap.is_veteran_verified is True


def test_dashboard_view_aggregates_latest(app):
    ent_ulid = _mk_entity()
    cust_ulid = _ensure_customer(ent_ulid)

    # T1 no crisis
    cust_svc.update_tier1(
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
    # T2 crisis (watchlist)
    cust_svc.update_tier2(
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

    # Mark as veteran
    cust_svc.set_veteran_verification(
        customer_ulid=cust_ulid,
        method="va_id",
        verified=True,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )

    dv = cust_svc.get_dashboard_view(cust_ulid)
    assert dv is not None
    assert dv.customer_ulid == cust_ulid
    assert dv.entity_ulid == ent_ulid
    assert dv.tier1_min == 2
    assert dv.tier2_min == 1
    assert dv.flag_tier1_immediate is False
    assert dv.watchlist is True
    assert dv.is_veteran_verified is True
    assert dv.veteran_method in (
        None,
        "va_id",
    )  # method lives on eligibility row
    assert "income" in dv.tier_factors["tier2"]
