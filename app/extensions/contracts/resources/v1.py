# app/extensions/contracts/v1.py
from __future__ import annotations

from app.extensions.contracts.types import ContractRequest, ContractResponse
from app.extensions.contracts.validate import load_schema, validate_payload
from app.lib.chrono import utc_now
from app.slices.resources import services as res_svc

# Schemas you’ll add beside this file:
# - schemas/resources.ensure_resource.request.json
# - schemas/resources.upsert_capabilities.request.json
# - schemas/resources.search.request.json  (optional; for POST search)
SCHEMA_ENSURE = load_schema(
    __file__, "schemas/resources.ensure_resource.request.json"
)
SCHEMA_UPSERT = load_schema(
    __file__, "schemas/resources.upsert_capabilities.request.json"
)
SCHEMA_SET_READINESS = load_schema(
    __file__, "schemas/resources.set_readiness.request.json"
)
SCHEMA_SET_MOU = load_schema(
    __file__, "schemas/resources.set_mou.request.json"
)
SCHEMA_REBUILD_IDX = load_schema(
    __file__, "schemas/resources.rebuild_index.request.json"
)
SCHEMA_PROMOTE_CLEAN = load_schema(
    __file__, "schemas/resources.promote_if_clean.request.json"
)
SCHEMA_PATCH = load_schema(
    __file__, "schemas/resources.patch_capabilities.request.json"
)
SCHEMA_REBUILD_ALL = load_schema(
    __file__, "schemas/resources.rebuild_all.request.json"
)


def patch_capabilities(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_PATCH, req["data"])
    hist_ulid = res_svc.patch_capabilities(
        resource_ulid=data["resource_ulid"],
        payload=data["capabilities"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = res_svc.resource_view(data["resource_ulid"])
    return {
        "contract": "resources.patch_capabilities.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"history_ulid": hist_ulid, "resource": view},
    }


def rebuild_all(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_REBUILD_ALL, req["data"])
    summary = res_svc.rebuild_all_capability_indexes(
        page=data.get("page", 1),
        per=data.get("per", 200),
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    return {
        "contract": "resources.rebuild_all.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": summary,
    }


def set_readiness(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_SET_READINESS, req["data"])
    res_svc.set_readiness_status(
        resource_ulid=data["resource_ulid"],
        status=data["status"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = res_svc.resource_view(data["resource_ulid"])
    return {
        "contract": "resources.set_readiness.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": view,
    }


def set_mou(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_SET_MOU, req["data"])
    res_svc.set_mou_status(
        resource_ulid=data["resource_ulid"],
        status=data["status"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = res_svc.resource_view(data["resource_ulid"])
    return {
        "contract": "resources.set_mou.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": view,
    }


def rebuild_index(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_REBUILD_IDX, req["data"])
    rows = res_svc.rebuild_capability_index(
        resource_ulid=data["resource_ulid"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = res_svc.resource_view(data["resource_ulid"])
    return {
        "contract": "resources.rebuild_index.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"rows": rows, "resource": view},
    }


def promote_if_clean(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_PROMOTE_CLEAN, req["data"])
    promoted = res_svc.promote_readiness_if_clean(
        resource_ulid=data["resource_ulid"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    view = res_svc.resource_view(data["resource_ulid"])
    return {
        "contract": "resources.promote_if_clean.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"promoted": promoted, "resource": view},
    }


def ensure_resource(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_ENSURE, req["data"])
    resource_ulid = res_svc.ensure_resource(
        entity_ulid=data["entity_ulid"],
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
    )
    return {
        "contract": "resources.ensure_resource.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"resource_ulid": resource_ulid},
    }


def upsert_capabilities(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_UPSERT, req["data"])
    hist_ulid = res_svc.upsert_capabilities(
        resource_ulid=data["resource_ulid"],
        payload=data[
            "capabilities"
        ],  # { "domain.key": {"has": bool, "note"?: str<=120}, ... }
        request_id=req["request_id"],
        actor_id=req.get("actor_ulid"),
        idempotency_key=req.get("idempotency_key") or req["request_id"],
    )
    # services already emit names-only ledger events; contract just returns the pointer
    view = res_svc.resource_view(data["resource_ulid"])
    return {
        "contract": "resources.upsert_capabilities.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"history_ulid": hist_ulid or None, "resource": view},
    }
