# tests/slices/calendar/test_calendar_routes_funding.py

from __future__ import annotations


def test_funding_demand_list_page_renders(staff_client):
    resp = staff_client.get("/calendar/funding-demands")
    assert resp.status_code == 200
    assert "Funding Demands" in resp.get_data(as_text=True)


def test_funding_demand_new_page_renders(staff_client):
    resp = staff_client.get("/calendar/funding-demands/new")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "New Funding Demand" in text
    assert "Funding demand title" in text
