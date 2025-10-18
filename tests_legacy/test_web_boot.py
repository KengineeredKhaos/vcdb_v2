import pytest


# @pytest.mark.xfail(
#     reason="auth.login link in template; Auth blueprint not wired in tests yet"
# )
def test_routes_index(client):
    r = client.get("/")
    assert r.status_code in (200, 302)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    j = r.get_json()
    assert j["status"] == "ok"
