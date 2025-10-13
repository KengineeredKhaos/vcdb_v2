# app/extensions/contracts/sponsors/v1.py
from __future__ import annotations

from app.extensions.contracts.types import ContractRequest, ContractResponse
from app.extensions.contracts.validate import load_schema, validate_payload
from app.lib.chrono import utc_now
from app.slices.sponsors import services as sp_svc

SCHEMA_ENSURE = load_schema(__file__, "schemas/sponsors.ensure.request.json")
SCHEMA_UPSERT_CAPS = load_schema(
    __file__, "schemas/sponsors.upsert_capabilities.request.json"
)
SCHEMA_PATCH_CAPS = load_schema(
    __file__, "schemas/sponsors.patch_capabilities.request.json"
)
SCHEMA_PLEDGE_UPSERT = load_schema(
    __file__, "schemas/sponsors.pledge_upsert.request.json"
)
SCHEMA_PLEDGE_STATUS = load_schema(
    __file__, "schemas/sponsors.pledge_set_status.request.json"
)


def ensure_sponsor(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_ENSURE, req["data"])
    sid = sp_svc.ensure_sponsor(
        entity_ulid=data["entity_ulid"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    return {
        "contract": "sponsors.ensure_sponsor.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"sponsor_ulid": sid},
    }


def upsert_capabilities(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_UPSERT_CAPS, req["data"])
    hist = sp_svc.upsert_capabilities(
        sponsor_ulid=data["sponsor_ulid"],
        payload=data["capabilities"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = sp_svc.sponsor_view(data["sponsor_ulid"])
    return {
        "contract": "sponsors.upsert_capabilities.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"history_ulid": hist, "sponsor": view},
    }


def patch_capabilities(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_PATCH_CAPS, req["data"])
    hist = sp_svc.patch_capabilities(
        sponsor_ulid=data["sponsor_ulid"],
        payload=data["capabilities"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = sp_svc.sponsor_view(data["sponsor_ulid"])
    return {
        "contract": "sponsors.patch_capabilities.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"history_ulid": hist, "sponsor": view},
    }


def pledge_upsert(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_PLEDGE_UPSERT, req["data"])
    pid = sp_svc.upsert_pledge(
        sponsor_ulid=data["sponsor_ulid"],
        pledge=data["pledge"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = sp_svc.sponsor_view(data["sponsor_ulid"])
    return {
        "contract": "sponsors.pledge.upsert.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"pledge_ulid": pid, "sponsor": view},
    }


def pledge_set_status(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_PLEDGE_STATUS, req["data"])
    sp_svc.set_pledge_status(
        pledge_ulid=data["pledge_ulid"],
        status=data["status"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    return {
        "contract": "sponsors.pledge.set_status.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {},
    }
