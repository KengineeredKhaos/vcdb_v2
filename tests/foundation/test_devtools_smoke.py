# tests/foundation/test_devtools_smoke.py
import pytest

def _get_json(client, path, **kwargs):
    r = client.get(path, **kwargs)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.get_data(as_text=True)}"
    return r.get_json()

def test_api_dev_health_endpoints_ok(client):
    d = _get_json(client, "/api/dev/health/db")
    assert "fk_enforced" in d and isinstance(d["fk_enforced"], bool)

    s = _get_json(client, "/api/dev/health/session")
    assert s.get("per_request_sessions") is True

def test_seed_manifest_shape(client):
    m = _get_json(client, "/api/dev/seed/manifest")
    for k in ("entities", "customers", "resources", "sponsors", "skus"):
        assert k in m and isinstance(m[k], int), f"missing/count not int: {k} -> {m.get(k)}"

def test_devtools_debug_user_header_stub_admin(client):
    # Baseline (no headers): in testing this may be unauthenticated; don't assert strict shape
    _ = _get_json(client, "/dev/debug/user")

    # With RBAC stub header: must present an admin user
    j = _get_json(client, "/dev/debug/user", headers={"X-Auth-Stub": "admin"})
    assert j["has_user"] is True
    assert "admin" in [r.lower() for r in (j.get("roles") or [])]
    assert j["is_admin"] is True
    assert j["is_authenticated"] is True

    # With domain stub as well
    j2 = _get_json(
        client,
        "/dev/debug/user",
        headers={"X-Auth-Stub": "admin", "X-Domain-Stub": "governor"},
    )
    assert "governor" in [r.lower() for r in (j2.get("domain_roles") or [])]

def test_devtools_whoami_header_stub_admin(client):
    r = client.get("/dev/whoami", headers={"X-Auth-Stub": "admin"})
    # Some implementations return JSON 200; others might 204 with no body — accept both
    assert r.status_code in (200, 204), f"/dev/whoami -> {r.status_code}: {r.get_data(as_text=True)}"
