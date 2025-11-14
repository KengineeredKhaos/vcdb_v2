# tests/foundation/test_governance_policies_validation.py
def test_governance_policies_validation_smoke(client):
    # Index with validation
    r = client.get("/api/v2/governance/policies?validate=1")
    assert r.status_code == 200
    d = r.get_json()
    assert d.get("ok") is True
    assert isinstance(d.get("policies"), list)

    # Every item has the validation keys (either None / [] when not applicable)
    for item in d["policies"]:
        assert {"key","filename","domains","focus","has_schema"}.issubset(item.keys())
        assert "schema_valid" in item  # can be True|False|None
        assert "schema_errors" in item # list
        if item["has_schema"] and item["schema_valid"] is False:
            # if invalid, we should have at least one error message
            assert isinstance(item["schema_errors"], list) and item["schema_errors"]

    # If at least one policy exists, check the detail endpoint
    if d["policies"]:
        k = d["policies"][0]["key"]
        r2 = client.get(f"/api/v2/governance/policies/{k}?validate=1")
        assert r2.status_code in (200, 404)
        if r2.status_code == 200:
            g = r2.get_json()
            assert g.get("ok") is True
            assert g.get("key") == k
            assert "schema_valid" in g and "schema_errors" in g
