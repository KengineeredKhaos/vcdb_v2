from __future__ import annotations

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.seeds.core import seed_minimal_customer
from app.slices.customers.models import CustomerEligibility
from app.slices.ledger.models import LedgerEvent
from app.slices.logistics.issuance_services import (
    IssueContext,
    decide_issue,
    decide_and_issue_one,
)
from app.slices.logistics.services import (
    ensure_location,
    ensure_item,
    receive_inventory,
)
from app.slices.logistics.models import InventoryStock, Issue


def _make_customer_veteran(*, is_veteran: bool) -> str:
    res = seed_minimal_customer(first="Test", last="Veteran", sess=db.session)
    elig = (
        db.session.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == res.customer_ulid)
        .one()
    )
    elig.is_veteran_verified = bool(is_veteran)
    db.session.commit()
    return res.customer_ulid


def test_decide_issue_unrestricted_allows_without_profile():
    customer_ulid = _make_customer_veteran(is_veteran=False)

    ctx = IssueContext(
        customer_ulid=customer_ulid,
        sku_code="AC-GL-LC-L-LB-U-00B",  # issuance_class=U => always allowed
        when_iso=now_iso8601_ms(),
    )
    d = decide_issue(ctx)
    assert d.allowed is True
    assert d.reason == "ok_unrestricted"


def test_issue_write_path_decrements_stock_and_emits_ledger_event():
    # customer eligibility doesn't matter for issuance_class=U
    customer_ulid = _make_customer_veteran(is_veteran=False)

    # Location + catalog item + initial stock
    loc_ulid = ensure_location(code="MAIN", name="Main Warehouse")

    sku = "AC-GL-LC-L-LB-U-00B"
    item_ulid = ensure_item(
        category="AC/GL",
        name="Gloves",
        unit="each",
        condition="new",
        sku=sku,
    )
    receipt = receive_inventory(
        item_ulid=item_ulid,
        quantity=5,
        unit="each",
        source="LC",
        received_at_utc=now_iso8601_ms(),
        location_ulid=loc_ulid,
        note="test receipt",
        actor_ulid=None,
        source_entity_ulid=None,
    )

    # decision + issuance
    ctx = IssueContext(
        customer_ulid=customer_ulid,
        sku_code=sku,
        location_ulid=loc_ulid,
        batch_ulid=receipt["batch_ulid"],
        when_iso=now_iso8601_ms(),
        actor_ulid=None,
    )

    decision = decide_issue(ctx)
    assert decision.allowed is True

    result = decide_and_issue_one(
        ctx=ctx,
        qty_each=2,
        decision=decision,
        request_id=None,
        reason="pytest",
        note="issued",
    )
    assert result.ok is True
    assert result.issue_ulid is not None

    # Caller commits in this design
    db.session.commit()

    # Stock decremented
    stock = (
        db.session.query(InventoryStock)
        .filter(
            InventoryStock.item_ulid == item_ulid,
            InventoryStock.location_ulid == loc_ulid,
        )
        .one()
    )
    assert stock.quantity == 3

    # Issue fact recorded
    issue = db.session.get(Issue, result.issue_ulid)
    assert issue is not None
    assert issue.customer_ulid == customer_ulid
    assert issue.sku_code == sku

    # Ledger event emitted via event_bus
    ev = (
        db.session.query(LedgerEvent)
        .filter(
            LedgerEvent.domain == "logistics",
            LedgerEvent.operation == "issue",
        )
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )
    assert ev is not None
    assert ev.target_ulid == customer_ulid
