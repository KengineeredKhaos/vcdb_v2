# tests/foundation/test_request_db_hygiene.py
def test_fk_enforced(client):
    r = client.get("/api/dev/health/db")
    assert r.status_code == 200
    d = r.get_json()
    assert d["fk_enforced"] is True

def test_session_lifecycle_guard(client):
    r = client.get("/api/dev/health/session")
    assert r.status_code == 200
    d = r.get_json()
    assert d["per_request_sessions"] is True
