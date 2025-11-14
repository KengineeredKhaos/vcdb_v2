# tests/foundation/test_contracts_readonly.py
# Verify that all v2 GET contracts return pinned DTO shapes and perform no writes.
PINNED_DTO_KEYS = {
    "entity": {"ulid","kind","created_at","updated_at"},
    "customer": {"ulid","entity_ulid","created_at"},
    "resource": {"ulid","entity_ulid","classifications","created_at"},
    "sponsor": {"ulid","entity_ulid","status","created_at"},
}

def test_v2_contracts_readonly_shapes(client, ro_session):
    # Entity GET
    r = client.get("/api/v2/entity/sample")  # route should return a sample DTO
    assert r.status_code == 200
    d = r.get_json()
    assert set(d.keys()) == PINNED_DTO_KEYS["entity"]

    # Resource/Sponsor/Customer GETs similar:
    for path, key in [
        ("/api/v2/customers/sample", "customer"),
        ("/api/v2/resources/sample", "resource"),
        ("/api/v2/sponsors/sample", "sponsor"),
    ]:
        rr = client.get(path)
        assert rr.status_code == 200
        dd = rr.get_json()
        assert set(dd.keys()) == PINNED_DTO_KEYS[key]

def test_v2_contracts_do_not_write(client, ro_session):
    # Snapshot a count, call GETs, ensure counts unchanged.
    from app.slices.entity.models import Entity
    before = ro_session.query(Entity).count()
    for path in [
        "/api/v2/entity/sample",
        "/api/v2/customers/sample",
        "/api/v2/resources/sample",
        "/api/v2/sponsors/sample",
    ]:
        assert client.get(path).status_code == 200
    after = ro_session.query(Entity).count()
    assert after == before
