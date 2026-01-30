from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.logistics.models import InventoryItem, InventoryStock, Location
from app.slices.logistics.issuance_services import available_skus_for_customer
from app.slices.logistics.sku import parse_sku


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
        sku_seq=0,  # test doesn't care; cadence is patched by policy in this test
    )


def _policy(*, sku_vet: str, sku_hml: str, sku_open: str) -> dict:
    return {
        "issuance": {
            "default_behavior": "allow",
            "defaults": {"cadence": {}},
        },
        "sku_constraints": {
            "defaults": {"cadence": {}},
            "rules": [
                {"match": {"sku": sku_vet}, "qualifiers": {"veteran_required": True}, "cadence": {}},
                {"match": {"sku": sku_hml}, "qualifiers": {"homeless_required": True}, "cadence": {}},
                {"match": {"sku": sku_open}, "qualifiers": {}, "cadence": {}},
            ],
        },
    }


def test_available_skus_filters_using_customer_cues(monkeypatch, app):
    import app.slices.logistics.issuance_services as iss

    # NOTE: issuance_class must be one of [V,H,D,U] per sku.py.
    sku_vet = "AC-GL-LC-L-LB-V-00B"
    sku_hml = "AC-GL-LC-L-LB-H-00C"
    sku_open = "AC-GL-LC-L-LB-U-00D"

    pol = _policy(sku_vet=sku_vet, sku_hml=sku_hml, sku_open=sku_open)
    monkeypatch.setattr(iss, "load_policy_logistics_issuance", lambda: pol)

    # No blackout
    import app.extensions.enforcers as enforcers
    monkeypatch.setattr(enforcers, "calendar_blackout_ok", lambda ctx: (True, {}))

    # Count contract calls: should be exactly one per call
    calls = {"n": 0}
    from app.extensions.contracts.customers_v2 import CustomerCuesDTO

    def _fake_get_customer_cues(customer_ulid: str) -> CustomerCuesDTO:
        calls["n"] += 1
        return CustomerCuesDTO(
            customer_ulid=customer_ulid,
            tier1_min=None,
            tier2_min=None,
            tier3_min=None,
            is_veteran_verified=True,    # eligible for sku_vet
            is_homeless_verified=False,  # NOT eligible for sku_hml
            flag_tier1_immediate=False,
            watchlist=False,
            watchlist_since_utc=None,
            as_of_iso="2026-01-28T00:00:00.000Z",
        )

    monkeypatch.setattr(iss, "get_customer_cues", _fake_get_customer_cues)

    with app.app_context():
        loc = Location(ulid=new_ulid(), code="WH1", name="Warehouse 1")
        db.session.add(loc)

        i1 = _mk_item(sku=sku_vet)
        i2 = _mk_item(sku=sku_hml)
        i3 = _mk_item(sku=sku_open)
        db.session.add_all([i1, i2, i3])

        # Ensure parents exist before inserting stock rows (avoids FK ordering edge cases)
        db.session.flush()

        s1 = InventoryStock(ulid=new_ulid(), item_ulid=i1.ulid, location_ulid=loc.ulid, quantity=5, unit="each")
        s2 = InventoryStock(ulid=new_ulid(), item_ulid=i2.ulid, location_ulid=loc.ulid, quantity=5, unit="each")
        s3 = InventoryStock(ulid=new_ulid(), item_ulid=i3.ulid, location_ulid=loc.ulid, quantity=5, unit="each")
        db.session.add_all([s1, s2, s3])

        db.session.commit()

        skus = available_skus_for_customer(
            customer_ulid="01CUST00000000000000000000",
            location_ulid=loc.ulid,
            include_out_of_stock=False,
        )

    assert calls["n"] == 1, "expected one get_customer_cues() call for the whole SKU list"
    assert sku_vet in skus
    assert sku_open in skus
    assert sku_hml not in skus
