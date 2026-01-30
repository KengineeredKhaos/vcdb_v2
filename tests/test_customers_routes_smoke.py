# tests/test_customers_routes_smoke.py
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import entity_v2
from app.lib.ids import new_ulid
from app.slices.customers.models import CustomerEligibility, CustomerHistory


@pytest.fixture
def customer_ulid(staff_client):
    ent = entity_v2.ensure_person(
        db.session,
        first_name="Fixture",
        last_name="Customer",
        email=f"fixture-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    resp = staff_client.post(
        "/customers", json={"entity_ulid": ent.entity_ulid}
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["ulid"]


def test_customers_post_requires_entity_ulid(staff_client):
    resp = staff_client.post("/customers", json={})
    assert resp.status_code == 400


def test_customers_smoke_create_view_update_tier1(staff_client):
    # 1) Create an Entity(person) via contract (PII stays in Entity slice)
    ent = entity_v2.ensure_person(
        db.session,
        first_name="Smoke",
        last_name="Test",
        email="smoke@test.invalid",  # give it something stable
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    entity_ulid = ent.entity_ulid

    # 2) Create customer via route
    resp = staff_client.post("/customers", json={"entity_ulid": entity_ulid})
    assert resp.status_code == 200, resp.get_json()
    customer_ulid = resp.get_json()["data"]["ulid"]
    assert customer_ulid == entity_ulid

    # 3) View customer via route
    resp = staff_client.get(f"/customers/{customer_ulid}")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["ulid"] == customer_ulid

    # 4) Update tier1
    resp = staff_client.post(
        f"/customers/{customer_ulid}/needs/tier1", json={}
    )
    assert resp.status_code == 200
    hist_ulid = resp.get_json()["data"]["history_ulid"]
    assert db.session.get(CustomerHistory, hist_ulid) is not None

    # 5) Eligibility row exists
    elig = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == customer_ulid)
        .one_or_none()
    )
    assert elig is not None


def test_customer_create_also_creates_eligibility(staff_client):
    ent = entity_v2.ensure_person(
        db.session,
        first_name="Elig",
        last_name="Test",
        email="elig@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    resp = staff_client.post(
        "/customers", json={"entity_ulid": ent.entity_ulid}
    )
    assert resp.status_code == 200, resp.get_json()

    customer_ulid = resp.get_json()["data"]["ulid"]
    elig = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == customer_ulid)
        .one_or_none()
    )
    assert elig is not None


def test_customer_needs_tier1_rejects_unknown_factor(
    staff_client, customer_ulid
):
    resp = staff_client.post(
        f"/customers/{customer_ulid}/needs/tier1",
        json={"food": 2, "NOPE": 2},
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_customer_needs_tier1_sets_homelessness(staff_client, customer_ulid):
    resp = staff_client.post(
        f"/customers/{customer_ulid}/needs/tier1",
        json={"housing": 1},  # others omitted => service fills them with None
    )
    assert resp.status_code == 200

    elig = (
        db.session.query(CustomerEligibility)
        .filter_by(customer_ulid=customer_ulid)
        .one()
    )
    assert elig.is_homeless_verified is True


def test_customer_needs_tier2_and_tier3_write_history(staff_client):
    ent = entity_v2.ensure_person(
        db.session,
        first_name="Needs",
        last_name="Test",
        email="needs@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )
    resp = staff_client.post(
        "/customers", json={"entity_ulid": ent.entity_ulid}
    )
    assert resp.status_code == 200, resp.get_json()
    customer_ulid = resp.get_json()["data"]["ulid"]

    resp = staff_client.post(
        f"/customers/{customer_ulid}/needs/tier2", json={}
    )
    assert resp.status_code == 200, resp.get_json()
    h2 = resp.get_json()["data"]["history_ulid"]
    assert db.session.get(CustomerHistory, h2) is not None

    resp = staff_client.post(
        f"/customers/{customer_ulid}/needs/tier3", json={}
    )
    assert resp.status_code == 200, resp.get_json()
    h3 = resp.get_json()["data"]["history_ulid"]
    assert db.session.get(CustomerHistory, h3) is not None
