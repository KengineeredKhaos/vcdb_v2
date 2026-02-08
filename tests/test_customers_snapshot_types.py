from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import customers_v2, entity_v2
from app.lib.ids import new_ulid
from app.slices.customers import services as cust_svc


def test_customers_eligibility_snapshot_is_typed(staff_client):
    # Create Entity(person) then Customer (via route)
    ent = entity_v2.ensure_person(
        db.session,
        first_name="Snap",
        last_name="Typed",
        email=f"snap-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    resp = staff_client.post(
        "/customers", json={"entity_ulid": ent.entity_ulid}
    )
    assert resp.status_code == 200, resp.get_json()

    customer_ulid = (resp.get_json().get("data") or {}).get(
        "ulid"
    ) or ent.entity_ulid

    snap = cust_svc.get_eligibility_snapshot(customer_ulid)
    assert snap is not None
    assert isinstance(snap, cust_svc.CustomerEligibilitySnapshot)

    # Ensure contract path still works and returns DTOs without dict/object guards.
    cues = customers_v2.get_customer_cues(customer_ulid)
    assert cues.customer_ulid == customer_ulid
