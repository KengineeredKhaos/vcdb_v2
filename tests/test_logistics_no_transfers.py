from __future__ import annotations


def test_inventory_transfers_not_permitted():
    """By design, stock only moves *into* inventory (receipt) and *out* to a Customer (issue).

    No location-to-location transfer API should exist in Logistics.
    """

    import app.slices.logistics.services as svc

    assert not hasattr(svc, "transfer_inventory")
