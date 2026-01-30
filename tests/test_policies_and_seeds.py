# tests/test_policies_and_seeds.py
from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.policies import load_policy_catalog, load_policy_locations
from app.seeds import core as seed_core
from app.seeds.core import seed_minimal_customer
from app.slices.customers.models import CustomerEligibility


@pytest.fixture(scope="session", autouse=True)
def seed_baseline_once(app_ctx):
    """
    Seed baseline *once* for the entire test session.
    IMPORTANT: schema is already built by conftest via Alembic.
    """
    faker = seed_core.make_faker(1337)
    seed_core.seed_policy_codes_no_commit(db.session)
    # keep this minimal; tests can create their own customers/resources as needed
    db.session.commit()
    yield


def test_policy_catalog_loads():
    catalog = load_policy_catalog()
    assert isinstance(catalog, dict)
    assert "locations" in catalog
    assert "logistics_issuance" in catalog


def test_locations_policy_shape():
    pol = load_policy_locations()
    assert "locations" in pol
    codes = {x["code"] for x in pol["locations"]}
    assert "MAIN" in codes


def test_seed_minimal_customer_creates_eligibility():
    res = seed_minimal_customer(
        first="Test", last="Customer", sess=db.session
    )
    elig = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == res.customer_ulid)
        .one_or_none()
    )
    assert elig is not None
