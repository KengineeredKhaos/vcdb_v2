# tests/foundation/test_auth_governannce_role_catalogs.py
def test_role_catalogs_exposed_without_pii(client):
    # auth_v2: RBAC role codes
    r = client.get("/api/v2/auth/roles")
    assert r.status_code == 200
    data = r.get_json()
    assert {"admin","auditor","staff","user"}.issubset(set(data["roles"]))
    # governance_v2: domain role codes + mapping
    r = client.get("/api/v2/governance/roles")
    assert r.status_code == 200
    g = r.get_json()
    assert "roles" in g and isinstance(g["roles"], list)
    assert "rbac_to_domain" in g and isinstance(g["rbac_to_domain"], dict)
    # PII guard
    serialized = r.get_data(as_text=True)
    assert all(k not in serialized.lower() for k in ["email", "phone", "address"])
