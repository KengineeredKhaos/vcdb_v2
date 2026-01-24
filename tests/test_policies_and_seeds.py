from __future__ import annotations

from app.extensions import db
from app.extensions.policies import load_policy_catalog, load_policy_locations
from app.seeds.core import seed_minimal_customer
from app.slices.customers.models import CustomerEligibility


def test_policy_catalog_loads():
    catalog = load_policy_catalog()
    assert isinstance(catalog, dict)
    # a few expected policy keys
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
    # eligibility row must exist
    elig = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == res.customer_ulid)
        .one_or_none()
    )
    assert elig is not None
