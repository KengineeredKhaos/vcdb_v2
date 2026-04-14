from __future__ import annotations


def test_activities_route_renders_empty_period(client):
    res = client.get("/finance/activities?period=2099-12")
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "Statement of Activities" in text
    assert "No activity for this period." in text, text
    print(text)
