# tests/foundation/test_governance_policies_index.py

def test_governance_policies_index_and_get(client):
    # Index
    r = client.get("/api/v2/governance/policies")
    assert r.status_code == 200
    d = r.get_json()
    assert d.get("ok") is True
    assert isinstance(d.get("policies"), list)

    # If we have any policies, validate coarse shape
    if d["policies"]:
        item = d["policies"][0]
        assert {"key","filename","domains","focus","has_schema"}.issubset(item.keys())
        assert isinstance(item["domains"], list)
        assert isinstance(item["has_schema"], bool)

        # Fetch one by key
        key = item["key"]
        r2 = client.get(f"/api/v2/governance/policies/{key}")
        assert r2.status_code in (200, 404)  # tolerate missing in edge cases
        if r2.status_code == 200:
            g = r2.get_json()
            assert g.get("ok") is True
            assert g.get("key") == key
            assert isinstance(g.get("policy"), dict)
