from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import customers_v2, entity_v2
from app.lib.ids import new_ulid
from app.slices.customers.models import CustomerEligibility
from app.slices.logistics.issuance_services import available_skus_for_customer
from app.slices.logistics.models import InventoryItem, InventoryStock, Location
from app.slices.logistics.sku import parse_sku


def _unique_sku(issuance_class: str) -> str:
    # seq must be 3 chars; ULID chars are safe uppercase base32
    suffix = new_ulid()[-3:]
    return f"AC-GL-LC-L-LB-{issuance_class}-{suffix}"


def _mk_item(*, sku: str) -> InventoryItem:
    p = parse_sku(sku)
    return InventoryItem(
        ulid=new_ulid(),
        category="logi_test",
        name=f"Item {sku}",
        unit="each",
        condition="new",
        sku=sku,
        sku_cat=p["cat"],
        sku_sub=p["sub"],
        sku_src=p["src"],
        sku_size=p["size"],
        sku_color=p["col"],
        sku_issuance_class=p["issuance_class"],
        sku_seq=0,
    )


def _policy(*, sku_vet: str, sku_hml: str) -> dict:
    # Keep cadence empty and patch _apply_cadence in the test to avoid
    # tying this integration test to Logistics cadence logic.
    return {
        "issuance": {
            "default_behavior": "allow",
            "defaults": {"cadence": {}},
        },
        "sku_constraints": {
            "defaults": {"cadence": {}},
            "rules": [
                {
                    "match": {"sku": sku_vet},
                    "qualifiers": {"veteran_required": True},
                    "cadence": {},
                },
                {
                    "match": {"sku": sku_hml},
                    "qualifiers": {"homeless_required": True},
                    "cadence": {},
                },
            ],
        },
    }


def test_available_skus_true_cross_slice_customer_create_then_cues_filter(
    monkeypatch, staff_client
):
    """
    True cross-slice integration:
      Entity.ensure_person -> POST /customers -> POST tier1 -> customers_v2.verify_veteran
      -> Logistics available_skus_for_customer() uses real customers_v2.get_customer_cues()
      to filter SKU candidates.

    We only monkeypatch Logistics' policy + blackout + cadence to keep the test scoped.
    """
    import app.slices.logistics.issuance_services as iss

    # 1) Create Entity(person) then Customer (exercise creation routine)
    ent = entity_v2.ensure_person(
        db.session,
        first_name="XSlice",
        last_name="Integration",
        email=f"xslice-{new_ulid()}@test.invalid",
        phone=None,
        request_id=new_ulid(),
        actor_ulid="seed",
    )

    resp = staff_client.post("/customers", json={"entity_ulid": ent.entity_ulid})
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json().get("data") or {}
    customer_ulid = (
        data.get("ulid")
        or data.get("customer_ulid")
        or data.get("entity_ulid")
        or ent.entity_ulid
    )
    # The canonical convention is customer_ulid == entity_ulid.
    # Some route variants may return customer_ulid/entity_ulid instead of ulid.
    assert customer_ulid == ent.entity_ulid

    # Sanity: created customer is visible via Customers contract read.
    assert customers_v2.get_dashboard_view(customer_ulid) is not None

    # 2) Update tier1 (exercise needs update route). Avoid homelessness trigger.
    resp = staff_client.post(
        f"/customers/{customer_ulid}/needs/tier1",
        json={"food": 2},  # shouldn't set homelessness
    )
    assert resp.status_code == 200, resp.get_json()

    # 3) Verify veteran via Customers contract write API (no direct DB pokes)
    vr = customers_v2.verify_veteran(
        customer_ulid=customer_ulid,
        method="dd214",
        verified=True,
        actor_ulid="seed",
        actor_has_governor=False,
        request_id=new_ulid(),
    )
    assert vr.customer_ulid == customer_ulid
    assert vr.is_veteran_verified is True

    # Sanity: eligibility row reflects veteran True and homeless False
    elig = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == customer_ulid)
        .one()
    )
    assert elig.is_veteran_verified is True
    assert elig.is_homeless_verified is False

    # Sanity: cues reflect the above (this is the cross-slice read surface)
    cues = customers_v2.get_customer_cues(customer_ulid)
    assert cues.customer_ulid == customer_ulid
    assert cues.is_veteran_verified is True
    assert cues.is_homeless_verified is False

    # 4) Seed Logistics inventory (3 SKUs):
    #    - veteran-only (V)
    #    - homeless-only (H)
    #    - open/unrestricted (U) (bypasses qualifiers entirely)
    sku_vet = _unique_sku("V")
    sku_hml = _unique_sku("H")
    sku_open = _unique_sku("U")

    loc = Location(ulid=new_ulid(), code=f"WH-{new_ulid()[-4:]}", name="Warehouse")
    db.session.add(loc)

    i1 = _mk_item(sku=sku_vet)
    i2 = _mk_item(sku=sku_hml)
    i3 = _mk_item(sku=sku_open)
    db.session.add_all([i1, i2, i3])
    db.session.flush()  # ensure parents exist before stock rows (SQLite FK ordering)

    db.session.add_all(
        [
            InventoryStock(
                ulid=new_ulid(),
                item_ulid=i1.ulid,
                location_ulid=loc.ulid,
                quantity=5,
                unit="each",
            ),
            InventoryStock(
                ulid=new_ulid(),
                item_ulid=i2.ulid,
                location_ulid=loc.ulid,
                quantity=5,
                unit="each",
            ),
            InventoryStock(
                ulid=new_ulid(),
                item_ulid=i3.ulid,
                location_ulid=loc.ulid,
                quantity=5,
                unit="each",
            ),
        ]
    )
    db.session.commit()

    # 5) Patch only *Logistics* externals for determinism (not Customers cues)
    monkeypatch.setattr(
        iss,
        "load_policy_logistics_issuance",
        lambda: _policy(sku_vet=sku_vet, sku_hml=sku_hml),
    )

    import app.extensions.enforcers as enforcers
    monkeypatch.setattr(enforcers, "calendar_blackout_ok", lambda ctx: (True, {}))

    monkeypatch.setattr(iss, "_apply_cadence", lambda rule, ctx: (True, None, None))

    # 6) Act: compute available SKUs for this customer at the location
    skus = available_skus_for_customer(
        customer_ulid=customer_ulid,
        location_ulid=loc.ulid,
        include_out_of_stock=False,
    )

    # 7) Assert: veteran-only and open are included; homeless-only excluded
    assert sku_vet in skus
    assert sku_open in skus
    assert sku_hml not in skus
