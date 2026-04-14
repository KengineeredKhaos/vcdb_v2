# tests/slices/customers/test_customer_route_access.py

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.extensions import db
from app.slices.admin.models import AdminInboxItem
from app.slices.customers.models import Customer
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
    assert_unauthenticated,
    login_and_settle_password,
    logout_if_possible,
    seed_real_auth_world,
)


@pytest.fixture()
def customer_seeded(app):
    """
    Seed only the customer rows this file actually needs.
    """
    seed_real_auth_world(
        app,
        customers=2,
        resources=0,
        sponsors=0,
        normalize_passwords=False,
    )
    return app


def _first_customer_entity_ulid(app) -> str:
    with app.app_context():
        value = (
            db.session.execute(
                select(Customer.entity_ulid).order_by(
                    Customer.entity_ulid.asc()
                )
            )
            .scalars()
            .first()
        )
        assert value, "expected at least one seeded customer"
        return value


def _customer_entity_ulids(app) -> list[str]:
    with app.app_context():
        values = (
            db.session.execute(
                select(Customer.entity_ulid).order_by(
                    Customer.entity_ulid.asc()
                )
            )
            .scalars()
            .all()
        )
        assert len(values) >= 2, "expected at least two seeded customers"
        return list(values)


def _extract_wiz_nonce(html: str) -> str:
    patterns = [
        r'name="wiz_nonce"\s+value="([^"]+)"',
        r'value="([^"]+)"\s+name="wiz_nonce"',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    raise AssertionError("wiz_nonce not found in response HTML")


def _count_customer_admin_items(
    app,
    *,
    entity_ulid: str,
    issue_kind: str,
) -> int:
    with app.app_context():
        return len(
            db.session.execute(
                select(AdminInboxItem)
                .where(AdminInboxItem.source_slice == "customers")
                .where(AdminInboxItem.issue_kind == issue_kind)
                .where(AdminInboxItem.subject_ref_ulid == entity_ulid)
            )
            .scalars()
            .all()
        )


def _drive_customer_to_review(
    client,
    *,
    entity_ulid: str,
    tier1_food: str,
) -> None:
    # eligibility
    resp = client.get(
        f"/customers/intake/{entity_ulid}/eligibility",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    nonce = _extract_wiz_nonce(resp.get_data(as_text=True))

    resp = client.post(
        f"/customers/intake/{entity_ulid}/eligibility",
        data={
            "wiz_nonce": nonce,
            "veteran_status": "verified",
            "veteran_method": "dd214",
            "housing_status": "housed",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}

    # tier 1
    resp = client.get(
        f"/customers/intake/{entity_ulid}/needs/tier1",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    nonce = _extract_wiz_nonce(resp.get_data(as_text=True))

    resp = client.post(
        f"/customers/intake/{entity_ulid}/needs/tier1",
        data={
            "wiz_nonce": nonce,
            "food": tier1_food,
            "hygiene": "sufficient",
            "health": "sufficient",
            "housing": "sufficient",
            "clothing": "sufficient",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}

    # tier 2
    resp = client.get(
        f"/customers/intake/{entity_ulid}/needs/tier2",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    nonce = _extract_wiz_nonce(resp.get_data(as_text=True))

    resp = client.post(
        f"/customers/intake/{entity_ulid}/needs/tier2",
        data={
            "wiz_nonce": nonce,
            "income": "sufficient",
            "employment": "sufficient",
            "transportation": "sufficient",
            "education": "sufficient",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}

    # tier 3
    resp = client.get(
        f"/customers/intake/{entity_ulid}/needs/tier3",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    nonce = _extract_wiz_nonce(resp.get_data(as_text=True))

    resp = client.post(
        f"/customers/intake/{entity_ulid}/needs/tier3",
        data={
            "wiz_nonce": nonce,
            "family": "sufficient",
            "peergroup": "sufficient",
            "tech": "sufficient",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}


def _complete_customer_review(
    client,
    *,
    entity_ulid: str,
) -> None:
    resp = client.get(
        f"/customers/intake/{entity_ulid}/review",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    nonce = _extract_wiz_nonce(resp.get_data(as_text=True))

    resp = client.post(
        f"/customers/intake/{entity_ulid}/complete",
        data={"wiz_nonce": nonce},
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}


def test_customer_operator_routes_require_authentication(
    client,
    customer_seeded,
):
    entity_ulid = _first_customer_entity_ulid(customer_seeded)

    paths = [
        "/customers/",
        f"/customers/{entity_ulid}",
        f"/customers/{entity_ulid}/history",
        f"/customers/{entity_ulid}/referrals/new",
        f"/customers/{entity_ulid}/referrals/outcomes/new",
        f"/customers/intake/{entity_ulid}/eligibility",
        f"/customers/intake/{entity_ulid}/review",
    ]

    for path in paths:
        resp = client.get(path, follow_redirects=False)
        assert_unauthenticated(resp)

    resp = client.post(
        f"/customers/intake/{entity_ulid}/eligibility",
        data={},
        follow_redirects=False,
    )
    assert_unauthenticated(resp)


def test_customer_legacy_admin_inbox_route_is_gone(client):
    resp = client.get("/customers/admin/inbox", follow_redirects=False)
    assert resp.status_code == 404


def test_customer_complete_sets_watchlist_and_publishes_admin_advisories(
    client,
    app,
    customer_seeded,  # only here so seeding runs
):
    entity_ulid = _customer_entity_ulids(app)[0]

    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    _drive_customer_to_review(
        client,
        entity_ulid=entity_ulid,
        tier1_food="immediate",
    )

    with app.app_context():
        customer = db.session.get(Customer, entity_ulid)
        assert customer is not None
        assert customer.tier1_min == 1
        assert customer.watchlist is True

    before_watchlist_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_watchlist_notice",
    )
    before_assessment_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_assessment_completed_notice",
    )

    _complete_customer_review(client, entity_ulid=entity_ulid)

    with app.app_context():
        customer = db.session.get(Customer, entity_ulid)
        assert customer is not None
        assert customer.intake_step == "complete"
        assert customer.intake_completed_at_iso is not None

    after_watchlist_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_watchlist_notice",
    )
    after_assessment_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_assessment_completed_notice",
    )

    assert after_watchlist_count >= 1
    assert after_watchlist_count in {
        before_watchlist_count,
        before_watchlist_count + 1,
    }
    assert after_assessment_count == before_assessment_count + 1

    with app.app_context():
        watchlist_rows = (
            db.session.execute(
                select(AdminInboxItem)
                .where(AdminInboxItem.source_slice == "customers")
                .where(
                    AdminInboxItem.issue_kind == "customer_watchlist_notice"
                )
                .where(AdminInboxItem.subject_ref_ulid == entity_ulid)
            )
            .scalars()
            .all()
        )
        assert watchlist_rows
        assert all(row.admin_status == "open" for row in watchlist_rows)
        assert all(
            row.workflow_key == "customer_advisory" for row in watchlist_rows
        )

        assessment_rows = (
            db.session.execute(
                select(AdminInboxItem)
                .where(AdminInboxItem.source_slice == "customers")
                .where(
                    AdminInboxItem.issue_kind
                    == "customer_assessment_completed_notice"
                )
                .where(AdminInboxItem.subject_ref_ulid == entity_ulid)
            )
            .scalars()
            .all()
        )
        assert assessment_rows
        assert assessment_rows[-1].admin_status == "open"
        assert assessment_rows[-1].workflow_key == "customer_advisory"


def test_customer_complete_without_watchlist_publishes_only_assessment_advisory(
    client,
    app,
    customer_seeded,  # only here so seeding runs
):
    entity_ulid = _customer_entity_ulids(app)[1]

    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    _drive_customer_to_review(
        client,
        entity_ulid=entity_ulid,
        tier1_food="sufficient",
    )

    with app.app_context():
        customer = db.session.get(Customer, entity_ulid)
        assert customer is not None
        assert customer.tier1_min != 1
        assert customer.watchlist is False

    before_watchlist_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_watchlist_notice",
    )
    before_assessment_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_assessment_completed_notice",
    )

    _complete_customer_review(client, entity_ulid=entity_ulid)

    with app.app_context():
        customer = db.session.get(Customer, entity_ulid)
        assert customer is not None
        assert customer.intake_step == "complete"
        assert customer.intake_completed_at_iso is not None

    after_watchlist_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_watchlist_notice",
    )
    after_assessment_count = _count_customer_admin_items(
        app,
        entity_ulid=entity_ulid,
        issue_kind="customer_assessment_completed_notice",
    )

    assert after_watchlist_count == before_watchlist_count
    assert after_assessment_count == before_assessment_count + 1

    with app.app_context():
        assessment_rows = (
            db.session.execute(
                select(AdminInboxItem)
                .where(AdminInboxItem.source_slice == "customers")
                .where(
                    AdminInboxItem.issue_kind
                    == "customer_assessment_completed_notice"
                )
                .where(AdminInboxItem.subject_ref_ulid == entity_ulid)
            )
            .scalars()
            .all()
        )
        assert assessment_rows
        assert assessment_rows[-1].admin_status == "open"
        assert assessment_rows[-1].workflow_key == "customer_advisory"


@pytest.mark.parametrize(
    ("username", "temporary_password", "settled_password"),
    [
        (ADMIN_USERNAME, ADMIN_TEMP_PASSWORD, ADMIN_SETTLED_PASSWORD),
        (STAFF_USERNAME, STAFF_TEMP_PASSWORD, STAFF_SETTLED_PASSWORD),
        (AUDITOR_USERNAME, AUDITOR_TEMP_PASSWORD, AUDITOR_SETTLED_PASSWORD),
    ],
)
def test_customer_operator_surfaces_allow_authenticated_users(
    client,
    customer_seeded,
    username: str,
    temporary_password: str,
    settled_password: str,
):
    entity_ulid = _first_customer_entity_ulid(customer_seeded)

    login_and_settle_password(
        client,
        username=username,
        temporary_password=temporary_password,
        settled_password=settled_password,
    )

    # Representative read surfaces
    resp = client.get("/customers/", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get(f"/customers/{entity_ulid}", follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/{entity_ulid}/history",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/{entity_ulid}/referrals/new",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/{entity_ulid}/referrals/outcomes/new",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/customers/intake/{entity_ulid}/eligibility",
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Representative mutate surface:
    # stale/missing nonce should redirect within the customer flow,
    # but it should not fail as unauthenticated/forbidden.
    resp = client.post(
        f"/customers/intake/{entity_ulid}/eligibility",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}

    logout_if_possible(client)
