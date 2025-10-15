# app/extensions/contracts/logistics/v1.py
from __future__ import annotations

from app.extensions.contracts.types import ContractRequest, ContractResponse
from app.extensions.contracts.validate import load_schema, validate_payload
from app.lib.chrono import now_iso8601_ms
from app.slices.logistics import services as logi

SCHEMA_LOC_ENS = load_schema(
    __file__, "schemas/logistics.location.ensure.request.json"
)
SCHEMA_ITEM_ENS = load_schema(
    __file__, "schemas/logistics.item.ensure.request.json"
)
SCHEMA_RECEIVE = load_schema(
    __file__, "schemas/logistics.inventory.receive.request.json"
)
SCHEMA_ISSUE = load_schema(
    __file__, "schemas/logistics.inventory.issue.request.json"
)
SCHEMA_TRANSFER = load_schema(
    __file__, "schemas/logistics.inventory.transfer.request.json"
)
SCHEMA_STOCK_RB = load_schema(
    __file__, "schemas/logistics.stock.rebuild.request.json"
)


def location_ensure(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_LOC_ENS, req["data"])
    ulid = logi.ensure_location(code=d["code"], name=d["name"])
    return {
        "contract": "logistics.location.ensure.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"location_ulid": ulid},
    }


def item_ensure(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_ITEM_ENS, req["data"])
    ulid = logi.ensure_item(
        category=d["category"],
        name=d["name"],
        unit=d["unit"],
        condition=d.get("condition", "mixed"),
        sku=d.get("sku"),
    )
    return {
        "contract": "logistics.item.ensure.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"item_ulid": ulid},
    }


def inventory_receive(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_RECEIVE, req["data"])
    out = logi.receive_inventory(
        item_ulid=d["item_ulid"],
        quantity=d["quantity"],
        unit=d["unit"],
        source=d["source"],
        received_at_utc=d["received_at_utc"],
        location_ulid=d["location_ulid"],
        source_entity_ulid=d.get("source_entity_ulid"),
        note=d.get("note"),
        actor_id=req.get("actor_ulid"),
    )
    return {
        "contract": "logistics.inventory.receive.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": out,
    }


def inventory_issue(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_ISSUE, req["data"])
    mid = logi.issue_inventory(
        batch_ulid=d["batch_ulid"],
        item_ulid=d["item_ulid"],
        quantity=d["quantity"],
        unit=d["unit"],
        location_ulid=d["location_ulid"],
        happened_at_utc=d["happened_at_utc"],
        target_ref_ulid=d.get("target_ref_ulid"),
        note=d.get("note"),
        actor_id=req.get("actor_ulid"),
    )
    return {
        "contract": "logistics.inventory.issue.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"movement_ulid": mid},
    }


def inventory_transfer(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_TRANSFER, req["data"])
    out = logi.transfer_inventory(
        item_ulid=d["item_ulid"],
        quantity=d["quantity"],
        unit=d["unit"],
        happened_at_utc=d["happened_at_utc"],
        location_from_ulid=d["location_from_ulid"],
        location_to_ulid=d["location_to_ulid"],
        note=d.get("note"),
        actor_id=req.get("actor_ulid"),
        batch_ulid=d.get("batch_ulid"),
    )
    return {
        "contract": "logistics.inventory.transfer.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": out,
    }


def stock_rebuild(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_STOCK_RB, req["data"])
    out = logi.rebuild_stock(
        item_ulid=d.get("item_ulid"), location_ulid=d.get("location_ulid")
    )
    return {
        "contract": "logistics.stock.rebuild.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": out,
    }
