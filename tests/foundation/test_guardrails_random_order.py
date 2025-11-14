# tests/foundation/test_guardrails_random_order.py
import random, itertools

ROUTES = [
    "/api/dev/health/db",
    "/api/dev/health/session",
    "/api/v2/auth/roles",
    "/api/v2/governance/roles",
    "/api/v2/entity/sample",
    "/api/v2/customers/sample",
    "/api/v2/resources/sample",
    "/api/v2/sponsors/sample",
    "/api/ledger/events?limit=10",
]

def test_routes_ok_in_random_order(client):
    for path in random.sample(ROUTES, len(ROUTES)):
        assert client.get(path).status_code == 200
