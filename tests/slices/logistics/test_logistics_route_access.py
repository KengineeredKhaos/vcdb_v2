# tests/slices/logistics/test_logistics_route_access.py

from __future__ import annotations

import pytest

from tests.support.real_auth import (
    ADMIN_SETTLED_PASSWORD,
    ADMIN_TEMP_PASSWORD,
    ADMIN_USERNAME,
    AUDITOR_SETTLED_PASSWORD,
    AUDITOR_TEMP_PASSWORD,
    AUDITOR_USERNAME,
    STAFF_SETTLED_PASSWORD,
    STAFF_TEMP_PASSWORD,
    STAFF_USERNAME,
    assert_forbidden,
    assert_unauthenticated,
    login_and_settle_password,
    logout_if_possible,
    seed_real_auth_world,
)


@pytest.fixture()
def logistics_seeded(app):
    seed_real_auth_world(
        app,
        customers=1,
        resources=0,
        sponsors=0,
        normalize_passwords=False,
    )
    return app


def _first_customer_ulid(app):
    from app.extensions import db
    from app.slices.customers.models import Customer

    with app.app_context():
        row = db.session.execute(
            db.select(Customer.entity_ulid).limit(1)
        ).first()
        assert row is not None
        return row[0]


def test_logistics_routes_require_authentication(client, logistics_seeded):
    customer_ulid = _first_customer_ulid(logistics_seeded)

    resp = client.get(
        f"/logistics/customers/{customer_ulid}/issue-cart",
        follow_redirects=False,
    )
    assert_unauthenticated(resp)

    resp = client.get(
        "/logistics/items/by-sku/TEST-SKU",
        follow_redirects=False,
    )
    assert_unauthenticated(resp)


def test_logistics_routes_deny_auditor(client, logistics_seeded):
    customer_ulid = _first_customer_ulid(logistics_seeded)

    login_and_settle_password(
        client,
        username=AUDITOR_USERNAME,
        temporary_password=AUDITOR_TEMP_PASSWORD,
        settled_password=AUDITOR_SETTLED_PASSWORD,
    )

    resp = client.get(
        f"/logistics/customers/{customer_ulid}/issue-cart",
        follow_redirects=False,
    )
    assert_forbidden(resp)

    resp = client.get(
        "/logistics/items/by-sku/TEST-SKU",
        follow_redirects=False,
    )
    assert_forbidden(resp)

    resp = client.post("/logistics/receive", json={}, follow_redirects=False)
    assert_forbidden(resp)

    logout_if_possible(client)


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (ADMIN_USERNAME, ADMIN_TEMP_PASSWORD, ADMIN_SETTLED_PASSWORD),
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
    ],
)
def test_logistics_routes_allow_staff_and_admin(
    client,
    logistics_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    customer_ulid = _first_customer_ulid(logistics_seeded)

    login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    resp = client.get(
        f"/logistics/customers/{customer_ulid}/issue-cart",
        follow_redirects=False,
    )
    assert resp.status_code in {200, 302, 400, 404}

    # resp = client.get(
    #     "/logistics/items/by-sku/TEST-SKU",
    #     follow_redirects=False,
    # )
    # assert resp.status_code in {200, 404}

    resp = client.post("/logistics/receive", json={}, follow_redirects=False)
    assert resp.status_code not in {401, 403}
