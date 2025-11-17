# tests/foundation/test_devtools_fake_writes.py
import pytest
import uuid

pytestmark = pytest.mark.skip(
    "Dev fake-write endpoints deprecated; using real service-backed routes."
)

ADMIN = {"X-Auth-Stub": "admin"}

ein = "%.9d" % (uuid.uuid4().int % 1_000_000_000)


def test_fake_person_create_then_list(client):
    r = client.post(
        "/api/v2/dev/fake/entity/person",
        json={"first_name": "Riley", "last_name": "Quinn"},
        headers=ADMIN,
    )
    assert r.status_code == 201
    p = r.get_json()["person"]
    assert p["ulid"] and p["entity_ulid"]

    r2 = client.get("/api/v2/entity/people", headers=ADMIN)
    assert r2.status_code == 200
    data = r2.get_json()
    assert any(row["ulid"] == p["ulid"] for row in data["data"])


def test_fake_org_create_and_assign_role_then_list(client):
    r = client.post(
        "/api/v2/dev/fake/entity/org",
        json={"legal_name": "Beacon Outreach", "ein": ein},
        headers=ADMIN,
    )
    assert r.status_code == 201
    o = r.get_json()["org"]

    r2 = client.post(
        "/api/v2/dev/fake/entity/role",
        json={"entity_ulid": o["entity_ulid"], "role": "resource"},
        headers=ADMIN,
    )
    assert r2.status_code == 201

    r3 = client.get("/api/v2/entity/orgs", headers=ADMIN)
    assert r3.status_code == 200
    data = r3.get_json()
    assert any(row["entity_ulid"] == o["entity_ulid"] for row in data["data"])
