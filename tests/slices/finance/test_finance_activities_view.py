from __future__ import annotations

import pytest

from tests.support.real_auth import (
    ADMIN_SETTLED_PASSWORD,
    ADMIN_TEMP_PASSWORD,
    ADMIN_USERNAME,
    login_and_settle_password,
    seed_real_auth_world,
)


@pytest.fixture()
def finance_seeded(app):
    seed_real_auth_world(
        app,
        customers=0,
        resources=0,
        sponsors=0,
        normalize_passwords=False,
    )
    return app


def test_activities_route_renders_empty_period(client, finance_seeded):
    login_and_settle_password(
        client,
        username=ADMIN_USERNAME,
        temporary_password=ADMIN_TEMP_PASSWORD,
        settled_password=ADMIN_SETTLED_PASSWORD,
    )

    res = client.get("/finance/activities?period=2099-12")
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "Statement of Activities" in text
    assert "No activity for this period." in text, text
    print(text)
