# tests/slices/sponsors/test_sponsors_routes_funding.py

from __future__ import annotations


def test_funding_opportunities_page_renders(staff_client):
    resp = staff_client.get("/sponsors/funding-opportunities")
    assert resp.status_code == 200
    assert "Funding Opportunities" in resp.get_data(as_text=True)


def test_new_funding_intent_page_renders(staff_client):
    resp = staff_client.get("/sponsors/funding-intents/new")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "New Funding Intent" in text
    assert "Funding Demand ULID" in text
