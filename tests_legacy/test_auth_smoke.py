# tests/test_auth_smoke.py
def test_login_page_renders(client):
    r = client.get("/auth/login")
    assert r.status_code == 200
