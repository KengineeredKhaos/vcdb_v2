from __future__ import annotations

import json

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.logistics.models import (
    InventoryBatch,
    InventoryMovement,
    InventoryStock,
    Issue,
)
from app.slices.logistics.services import (
    attach_issue_decision,
    count_issues_in_window,
    ensure_item,
    ensure_location,
    issue_inventory_lowlevel,
    nth_oldest_issue_at_in_window,
    receive_inventory,
)


def rackbin_code() -> str:
    seed = new_ulid()
    letters = "ABCDEF"
    a = letters[ord(seed[-1]) % 6]
    b = (ord(seed[-2]) % 3) + 1
    c = (ord(seed[-3]) % 3) + 1
    return f"MAIN-{a}{b}-{c}"


def unique_sku(issuance_class: str = "U") -> str:
    suffix = new_ulid()[-3:]  # ULID chars are safe uppercase base32
    return f"AC-GL-LC-L-LB-{issuance_class}-{suffix}"


def _seed_item_and_stock(*, qty: int) -> tuple[str, str, str, str]:
    """Return (loc_ulid, item_ulid, sku, batch_ulid)."""
    code = rackbin_code()  # MAIN-[A-F][1-3]-[1-3]
    loc_ulid = ensure_location(code=code, name=f"Rackbin {code}")

    sku = unique_sku("U")
    item_ulid = ensure_item(
        category="AC/GL",
        name="Gloves",
        unit="each",
        condition="new",
        sku=sku,
    )

    rec = receive_inventory(
        item_ulid=item_ulid,
        quantity=qty,
        unit="each",
        source="LC",
        received_at_utc="2026-01-01T00:00:00.000Z",
        location_ulid=loc_ulid,
        note="pytest receipt",
        actor_ulid=None,
        source_entity_ulid=None,
    )

    return loc_ulid, item_ulid, sku, rec["batch_ulid"]


def test_receive_inventory_creates_batch_receipt_movement_and_stock():
    loc_ulid, item_ulid, _sku, batch_ulid = _seed_item_and_stock(qty=4)

    b = db.session.get(InventoryBatch, batch_ulid)
    assert b is not None
    assert b.item_ulid == item_ulid
    assert b.location_ulid == loc_ulid
    assert b.quantity == 4
    assert b.unit == "each"  # normalized

    mv = (
        db.session.query(InventoryMovement)
        .filter(InventoryMovement.batch_ulid == batch_ulid)
        .one()
    )
    assert mv.kind == "receipt"
    assert mv.quantity == 4
    assert mv.unit == "each"  # normalized

    st = (
        db.session.query(InventoryStock)
        .filter(
            InventoryStock.item_ulid == item_ulid,
            InventoryStock.location_ulid == loc_ulid,
        )
        .one()
    )
    assert st.quantity == 4
    assert st.unit == "each"


def test_issue_inventory_lowlevel_creates_issue_movement_and_decrements_stock():
    loc_ulid, item_ulid, sku, batch_ulid = _seed_item_and_stock(qty=5)
    customer_ulid = (
        new_ulid()
    )  # customer_ulid is not a FK; ULID string is enough

    movement_ulid = issue_inventory_lowlevel(
        batch_ulid=batch_ulid,
        item_ulid=item_ulid,
        quantity=2,
        unit="each",
        location_ulid=loc_ulid,
        happened_at_utc="2026-01-01T00:05:00.000Z",
        target_ref_ulid=customer_ulid,
        note="pytest issue",
        actor_ulid=None,
    )

    st = (
        db.session.query(InventoryStock)
        .filter(
            InventoryStock.item_ulid == item_ulid,
            InventoryStock.location_ulid == loc_ulid,
        )
        .one()
    )
    assert st.quantity == 3

    mv = db.session.get(InventoryMovement, movement_ulid)
    assert mv is not None
    assert mv.kind == "issue"
    assert mv.quantity == 2
    assert mv.target_ref_ulid == customer_ulid

    issue = (
        db.session.query(Issue)
        .filter(Issue.movement_ulid == movement_ulid)
        .one()
    )
    assert issue.customer_ulid == customer_ulid
    assert issue.sku_code == sku
    assert issue.quantity == 2


def test_attach_issue_decision_persists_json():
    loc_ulid, item_ulid, _sku, batch_ulid = _seed_item_and_stock(qty=3)
    customer_ulid = new_ulid()

    movement_ulid = issue_inventory_lowlevel(
        batch_ulid=batch_ulid,
        item_ulid=item_ulid,
        quantity=1,
        unit="each",
        location_ulid=loc_ulid,
        happened_at_utc="2026-01-01T00:06:00.000Z",
        target_ref_ulid=customer_ulid,
        note=None,
        actor_ulid=None,
    )

    attach_issue_decision(
        movement_ulid,
        {"allowed": True, "reason": "pytest"},
    )

    issue = (
        db.session.query(Issue)
        .filter(Issue.movement_ulid == movement_ulid)
        .one()
    )
    assert issue.decision_json
    payload = json.loads(issue.decision_json)
    assert payload["allowed"] is True
    assert payload["reason"] == "pytest"


def test_issue_window_helpers_count_and_nth_oldest():
    loc_ulid, item_ulid, sku, batch_ulid = _seed_item_and_stock(qty=10)
    customer_ulid = new_ulid()

    t1 = "2026-01-01T00:00:10.000Z"
    t2 = "2026-01-01T00:00:11.000Z"
    t3 = "2026-01-01T00:00:12.000Z"

    # 3 issues at known timestamps
    for t in (t1, t2, t3):
        issue_inventory_lowlevel(
            batch_ulid=batch_ulid,
            item_ulid=item_ulid,
            quantity=1,
            unit="each",
            location_ulid=loc_ulid,
            happened_at_utc=t,
            target_ref_ulid=customer_ulid,
            note=None,
            actor_ulid=None,
        )

    c_all = count_issues_in_window(
        customer_ulid,
        sku_code=sku,
        window_start_iso=t1,
        as_of_iso=t3,
    )
    assert c_all == 3

    c_tail = count_issues_in_window(
        customer_ulid,
        sku_code=sku,
        window_start_iso=t2,
        as_of_iso=t3,
    )
    assert c_tail == 2

    nth = nth_oldest_issue_at_in_window(
        customer_ulid,
        n=2,
        sku_code=sku,
        window_start_iso=t1,
        as_of_iso=t3,
    )
    assert nth == t2
