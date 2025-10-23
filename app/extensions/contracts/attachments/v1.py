# app/extensions/contracts/attachments/v1.py
from __future__ import annotations

from app.extensions.contracts.types import ContractRequest, ContractResponse
from app.extensions.contracts.validate import load_schema, validate_payload
from app.lib.chrono import now_iso8601_ms
from app.slices.attachments import services as att_svc

SCHEMA_LINK = load_schema(__file__, "schemas/attachments.link.request.json")
SCHEMA_UNLINK = load_schema(
    __file__, "schemas/attachments.unlink.request.json"
)
SCHEMA_SIGNURL = load_schema(
    __file__, "schemas/attachments.signurl.request.json"
)
# Upload goes over route (multipart); contract can optionally wrap a pre-signed upload flow later.


def link(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_LINK, req["data"])
    link_ulid = att_svc.link_attachment(
        attachment_ulid=data["attachment_ulid"],
        slice_name=data["slice"],
        domain=data["domain"],
        target_ulid=data["target_ulid"],
        note=data.get("note"),
        request_id=req["request_id"],
        actor_ulid=req.get("actor_ulid"),
    )
    return {
        "contract": "attachments.link.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"link_ulid": link_ulid},
    }


def unlink(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_UNLINK, req["data"])
    att_svc.unlink_attachment(
        link_ulid=data["link_ulid"],
        request_id=req["request_id"],
        actor_ulid=req.get("actor_ulid"),
    )
    return {
        "contract": "attachments.unlink.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {},
    }


def sign_url(req: ContractRequest) -> ContractResponse:
    data = validate_payload(SCHEMA_SIGNURL, req["data"])
    url = att_svc.sign_url(
        attachment_ulid=data["attachment_ulid"],
        ttl_seconds=data.get("ttl_seconds", 300),
        request_id=req["request_id"],
        actor_ulid=req.get("actor_ulid"),
    )
    return {
        "contract": "attachments.sign_url.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"url": url},
    }
