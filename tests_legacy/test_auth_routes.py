from app import create_app


def test_auth_routes_exist(app):
    url_map = {r.endpoint for r in app.url_map.iter_rules()}
    # Public endpoints
    assert "auth.login" in url_map
    assert "auth.login_post" in url_map
    # Session endpoints
    assert "auth.logout" in url_map


def test_login_page_renders(client):
    r = client.get("/auth/login")
    assert r.status_code == 200
