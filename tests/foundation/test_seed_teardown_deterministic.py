# tests/foundation/test_seed_teardown_deterministic.py
def test_seed_is_deterministic(client):
    # Your seed command should expose counts/ULID ranges deterministically
    a = client.get("/api/dev/seed/manifest").get_json()
    b = client.get("/api/dev/seed/manifest").get_json()
    # Calling twice should not change the manifest
    assert a == b
    assert all(a[k] >= 1 for k in ["entities","customers","resources","sponsors","skus"])
