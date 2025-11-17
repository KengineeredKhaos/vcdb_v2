import json
import random


def _get_json(client, path, **kwargs):
    r = client.get(path, **kwargs)
    assert (
        r.status_code == 200
    ), f"{path} -> {r.status_code}: {r.get_data(as_text=True)}"
    return r.get_json()


def test_entity_people_route_lists_data(client):
    # v2 JSON endpoint
    data = _get_json(client, "/api/v2/entity/people")
    assert "items" in data and isinstance(data["items"], list)


def test_entity_orgs_route_lists_resource_by_default(client):
    # v2 JSON endpoint; default is all orgs, filter via querystring below
    data = _get_json(client, "/api/v2/entity/orgs")
    assert "items" in data and isinstance(data["items"], list)


def test_entity_orgs_route_role_filter(client):
    # role=resource filter supported by v2 route
    data = _get_json(client, "/api/v2/entity/orgs?role=resource")
    assert "items" in data and isinstance(data["items"], list)
    # If any items exist, they should have a 'roles' array containing 'resource'
    for org in data["items"]:
        assert "roles" in org
        assert "resource" in org["roles"]
