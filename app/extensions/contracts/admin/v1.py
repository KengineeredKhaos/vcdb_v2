# extensions/contracts/admin/v1.py
from typing import TypedDict, NotRequired
from datetime import datetime, timezone
from extensions.contracts.types import ContractRequest, ContractResponse


class RoleRepairRequest(TypedDict, total=False):
    entity_ulid: str
    add: NotRequired[list[str]]
    remove: NotRequired[list[str]]


class RoleRepairDTO(TypedDict):
    entity_ulid: str
    current_roles: list[str]
    result_roles: list[str]
    diff: dict  # {added:[...], removed:[...]}
    ledger_preview: dict  # present only in dry_run
    dry_run: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def role_repair(req: ContractRequest) -> ContractResponse:
    data: RoleRepairRequest = req["data"]  # type: ignore
    eid = data["entity_ulid"]
    to_add, to_remove = set(data.get("add", [])), set(data.get("remove", []))

    # 1) Current & allowed roles (replace with real services)
    current = ["customer"]
    allowed = {"customer", "resource", "sponsor", "governor"}

    bad_add = sorted(r for r in to_add if r not in allowed)
    bad_rm = sorted(r for r in to_remove if r not in allowed)
    if bad_add or bad_rm:
        errs = []
        if bad_add:
            errs.append(
                {
                    "code": "INVALID_ROLE",
                    "message": f"Unknown in add: {bad_add}",
                    "field": "add",
                }
            )
        if bad_rm:
            errs.append(
                {
                    "code": "INVALID_ROLE",
                    "message": f"Unknown in remove: {bad_rm}",
                    "field": "remove",
                }
            )
        return {
            "contract": "admin.role_repair.v1",
            "request_id": req["request_id"],
            "ts": _now(),
            "ok": False,
            "errors": errs,
        }

    result = sorted((set(current) | to_add) - to_remove)
    diff = {
        "added": sorted(set(result) - set(current)),
        "removed": sorted(set(current) - set(result)),
    }

    ledger_evt = {
        "type": "role.repaired",
        "domain": "governance",
        "operation": "update_roles",
        "happened_at_utc": _now(),
        "actor_ulid": req.get("actor_ulid"),
        "target_id": eid,
        "changed_fields_json": {
            "before": {"roles": current},
            "after": {"roles": result},
            "diff": diff,
        },
        "refs_json": {
            "contract": "admin.role_repair.v1",
            "request_id": req["request_id"],
        },
        "correlation_id": req["request_id"],
    }

    if req.get("dry_run", False):
        return {
            "contract": "admin.role_repair.v1",
            "request_id": req["request_id"],
            "ts": _now(),
            "ok": True,
            "data": RoleRepairDTO(
                entity_ulid=eid,
                current_roles=current,
                result_roles=result,
                diff=diff,
                ledger_preview=ledger_evt,
                dry_run=True,
            ),
        }

    # Commit path (pseudo):
    # entity_service.set_roles(eid, result)
    # ledger_service.emit(ledger_evt)
    return {
        "contract": "admin.role_repair.v1",
        "request_id": req["request_id"],
        "ts": _now(),
        "ok": True,
        "data": RoleRepairDTO(
            entity_ulid=eid,
            current_roles=current,
            result_roles=result,
            diff=diff,
            ledger_preview={},  # omit in commit
            dry_run=False,
        ),
        "ledger": {"emitted": True},  # you can include event_id if available
    }
