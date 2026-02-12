# Canonical Patterns for Services & Contracts

## Canonical usage patterns I’ll follow

### Service write (DB + ledger emit)

```python
# inside a slice service
from app.lib.db import commit_or_rollback
from app.lib.chrono import utc_now
from app.lib.request_ctx import ensure_request_id, get_actor_ulid
from app.extensions.event_bus import emit as emit_event

def assign_role(db, repo, entity_ulid: str, role: str) -> None:
    rid = ensure_request_id()
    with commit_or_rollback(db):
        repo.add_role(entity_ulid, role)
        emit_event(
            type="entity.role.assigned",
            slice="entity",
            request_id=rid,
            happened_at=utc_now(),
            actor_id=get_actor_ulid(),
            target_id=entity_ulid,
            operation="assigned",
            changed_fields={"role": role},
            refs={},
        )
```

### Contract wrapper (validate → call service → shaped response)

```python
# extensions/contracts/entity/v2.py
from app.extensions.contracts.types import ContractRequest, ContractResponse
from app.extensions.contracts.validate import load_schema, validate_payload
from app.lib.chrono import utc_now

SCHEMA = load_schema(__file__, "schemas/entity.add_role.request.json")

def add_role(req: ContractRequest) -> ContractResponse:
    validate_payload(SCHEMA, req["data"])
    entity_ulid = req["data"]["entity_ulid"]
    role = req["data"]["role"]
    # call into slice service (no cross-slice DB reach-ins)
    # entity_services.add_role(entity_ulid, role, actor=req.get("actor_ulid"), dry_run=req.get("dry_run", False))
    return {
        "contract": "entity.add_role.v2",
        "request_id": req["request_id"],
        "ts": utc_now(),
        "ok": True,
        "data": {"entity_ulid": entity_ulid, "role": role},
        # optionally: "ledger": {"event_id": "..."} on commit
    }
```

### JSON hashing / persistence (stable)

```python
from app.lib.jsonutil import stable_dumps
digest = stable_dumps(payload).encode("utf-8")
```

## Ledger DTO shape (v2 target)

Per your opening statement, I’ll standardize on:

```
event_ulid, domain, operation,
actor_id, target_id,
happened_at, request_id, correlation_id?,
changed_fields_json, refs_json,
prev_event_id, prev_hash, event_hash,
chain_key?  # optional
```

We’ll make sure Transactions’ `log_event`/append computes `event_hash` using **stable JSON** and enforces idempotency on `request_id`.

## How I’ll apply this right away

- Use `utc_now()` + `new_ulid()` everywhere (routes/services/contracts/tests).

- Contracts will always validate payloads with JSON Schema before calling services.

- Services will be the only place that touches slice DB; contracts never reach into another slice’s tables.

- All inter-slice calls go via `extensions/*` contracts; PRs will start with schema + DTOs.
