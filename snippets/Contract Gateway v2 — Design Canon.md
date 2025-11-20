# Contract Gateway v2 — Design Canon

> **Status:** Design-only, not implemented  
> **Scope:** How to expose extensions contracts over HTTP/RPC/queue *without* leaking internals, and how to map our runtime `ContractError` into a stable wire format.

## 1. Goals & Non-Goals

### Goals

- Provide a **single, consistent envelope** for calling any extensions contract.

- Keep slice internals untouched: gateway is **edge-only**.

- Map internal **`ContractError` exceptions ➜ structured wire errors**.

- Support **dry-run** semantics where contracts expose a dry_run flag.

- Be safe to log and ship: **no PII** in gateway errors or metadata.

### Non-Goals (for v1)

- No attempt at auto-discovery or fancy routing.

- No promise that every contract supports dry-run; gateway just forwards it where implemented.

- No change to existing extensions contracts or slices — they remain as-is.

---

## 2. Runtime vs Gateway Types

**Runtime error type (already canon):**

- `app/extensions/errors.py` → `class ContractError(RuntimeError)` with:
  
  - `code: str`
  
  - `where: str`
  
  - `message: str`
  
  - `http_status: int`
  
  - `data: dict | None`

**Gateway types (design):**

These are **wire shapes**, not Python exceptions. They live conceptually at the edge (HTTP/queue). Name them to avoid colliding with the runtime exception type.

Suggested names (Python view):

```python
class GatewayContractRequest(TypedDict):
    contract: str              # "governance_v2.get_poc_policy"
    request_id: str            # caller's correlation id
    ts: str                    # ISO8601 Z, when the request was made
    actor_ulid: NotRequired[str]
    dry_run: NotRequired[bool]
    data: dict                 # contract-specific payload

class GatewayError(TypedDict, total=False):
    code: str                  # mirrors ContractError.code
    where: str                 # mirrors ContractError.where
    message: str               # mirrors ContractError.message
    http_status: int           # mirrors ContractError.http_status
    data: NotRequired[dict]    # mirrors ContractError.data

class GatewayContractResponse(TypedDict, total=False):
    contract: str
    request_id: str
    ts: str                    # response timestamp
    ok: bool
    data: NotRequired[dict]    # contract-specific result on success
    warnings: NotRequired[list[str]]
    errors: NotRequired[list[GatewayError]]
    ledger: NotRequired[dict]  # optional ledger info (see below)
```

> **Key point:** internally, extensions continue to use `ContractError` (exception).  
> At the boundary, the gateway converts that exception to `GatewayError` inside a `GatewayContractResponse`.

---

## 3. Request Envelope (GatewayContractRequest)

Fields:

- `contract`
  
  - String key naming the contract function.
  
  - Recommendation: **exactly match the Python path you’d call**:
    
    - e.g. `"governance_v2.get_poc_policy"`, `"ledger_v2.emit"`, `"entity_v2.create_entity"`.

- `request_id`
  
  - Caller’s correlation ID. If missing, gateway may generate one but should still echo it in the response.

- `ts`
  
  - ISO8601 Z timestamp for when the caller created the request.

- `actor_ulid` *(optional)*
  
  - ULID of the user/system invoking the contract.

- `dry_run` *(optional)*
  
  - If true, gateway calls the contract in “preview” mode (if that contract supports it).

- `data`
  
  - Arbitrary JSON object. The gateway passes this to the contract in a contract-specific way (see next section).

---

## 4. How the Gateway Invokes Contracts

The basic pattern:

1. **Lookup** the target function for `contract`, e.g.:
   
   ```python
   from app.extensions.contracts import governance_v2, ledger_v2, entity_v2
   
   CONTRACTS = {
      "governance_v2.get_poc_policy": governance_v2.get_poc_policy,
      "ledger_v2.emit": ledger_v2.emit,
      "entity_v2.create_entity": entity_v2.create_entity,
      # ...
   }
   ```

2. Build a call from `data`.
   
   - The gateway is **not** magic: it knows, per contract, how to map `data` into kwargs.
   
   - Two common patterns:
     
     - Direct passthrough:
       
       ```python
       result = fn(**req["data"])
       ```
     
     - Or a small per-contract adapter.

3. Pass along `actor_ulid`, `request_id`, and `dry_run` where relevant:
   
   - Example for a dry-run aware contract:
     
     ```python
     result = entity_v2.create_entity(
        actor_ulid=req.get("actor_ulid"),
        request_id=req["request_id"],
        dry_run=req.get("dry_run", False),
        **req["data"],
     )
     ```

4. If the contract returns a DTO/dataclass, convert to `dict` for `GatewayContractResponse.data`.

---

## 5. Response Envelope (GatewayContractResponse)

On **success**:

```json
{
  "contract": "ledger_v2.emit",
  "request_id": "abc-123",
  "ts": "2025-11-18T08:30:00Z",
  "ok": true,
  "data": {
    "event_id": "01HXYZ...",
    "event_type": "governance.policy_updated",
    "chain_key": "governance"
  }
}
```

- `ok: true`

- `data`: contract-specific payload (often the DTO’s dict).

- `warnings`: optional list of strings.

- `errors`: absent or empty list.

On **error** (ContractError):

```json
{
  "contract": "governance_v2.get_poc_policy",
  "request_id": "abc-123",
  "ts": "2025-11-18T08:31:00Z",
  "ok": false,
  "errors": [
    {
      "code": "policy_missing",
      "where": "governance_v2.get_poc_policy",
      "message": "POC policy file not found",
      "http_status": 503,
      "data": {
        "path": "slices/governance/data/policy.poc.json"
      }
    }
  ]
}
```

- `ok: false`

- `errors` is a list, even though we typically only have one core `ContractError`.

---

## 6. Mapping `ContractError` → `GatewayError`

The gateway is responsible for catching `ContractError` and mapping fields 1:1 into a `GatewayError`:

**Runtime:**

```python
from app.extensions.errors import ContractError

try:
    result = contract_fn(...)
except ContractError as e:
    err = {
        "code": e.code,
        "where": e.where,
        "message": e.message,
        "http_status": e.http_status,
    }
    if e.data is not None:
        err["data"] = e.data

    response = {
        "contract": req["contract"],
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": False,
        "errors": [err],
    }
```

**Notes:**

- `http_status` field in the `GatewayError` comes directly from the exception.
  
  - The HTTP *response* status code (for an HTTP gateway) can mirror that:
    
    - e.g. HTTP 400 when `http_status` is 400, etc.

- **No PII** in `code`, `where`, `message`, `data` — enforced by your internal rules for `ContractError`.

---

## 7. Ledger Info in the Gateway (`ledger` field)

Some contracts (especially write paths) may emit ledger events as a side effect.

If you ever want the gateway to expose “what ledger event got created,” use the `ledger` field:

Example response shape:

```json
{
  "contract": "ledger_v2.emit",
  "request_id": "abc-123",
  "ts": "2025-11-18T08:30:00Z",
  "ok": true,
  "data": {
    "event_id": "01HXYZ...",
    "event_type": "governance.policy_updated",
    "chain_key": "governance"
  },
  "ledger": {
    "event_id": "01HXYZ...",
    "chain_key": "governance"
  }
}
```

Guidelines:

- `ledger` should be **PII-free** (event ULID, chain_key, maybe domain/operation).

- It’s **optional**; not all contracts emit ledger events.

---

## 8. HTTP Gateway Sketch (for future implementation)

If/when someone builds an HTTP gateway, the pattern should be:

- **Input:** JSON body → `GatewayContractRequest`.

- **Output:** JSON body → `GatewayContractResponse`.

Very rough outline:

```python
from flask import Blueprint, request, jsonify
from app.extensions.errors import ContractError
from app.extensions.contracts import governance_v2, ledger_v2, entity_v2
from app.lib.chrono import now_iso8601_ms

bp = Blueprint("gateway", __name__, url_prefix="/api/contracts")

CONTRACTS = {
    "governance_v2.get_poc_policy": governance_v2.get_poc_policy,
    "ledger_v2.emit": ledger_v2.emit,
    "entity_v2.create_entity": entity_v2.create_entity,
    # ...
}

@bp.post("/")
def call_contract():
    req_json = request.get_json(force=True)
    contract_key = req_json["contract"]
    fn = CONTRACTS.get(contract_key)
    if not fn:
        # Minimally structured error; not a ContractError
        return jsonify({
            "contract": contract_key,
            "request_id": req_json.get("request_id"),
            "ts": now_iso8601_ms(),
            "ok": False,
            "errors": [{
                "code": "unknown_contract",
                "where": "gateway.http_v1",
                "message": f"no such contract: {contract_key}",
                "http_status": 404,
                "data": {},
            }],
        }), 404

    try:
        # Very simple: pass req_json["data"] as **kwargs; add request_id/actor as needed
        result = fn(**req_json.get("data", {}))
        body = {
            "contract": contract_key,
            "request_id": req_json.get("request_id"),
            "ts": now_iso8601_ms(),
            "ok": True,
            "data": getattr(result, "to_dict", lambda: result)(),
        }
        return jsonify(body), 200

    except ContractError as e:
        err = {
            "code": e.code,
            "where": e.where,
            "message": e.message,
            "http_status": e.http_status,
        }
        if e.data:
            err["data"] = e.data
        body = {
            "contract": contract_key,
            "request_id": req_json.get("request_id"),
            "ts": now_iso8601_ms(),
            "ok": False,
            "errors": [err],
        }
        return jsonify(body), e.http_status
```

You don’t need to implement this now; it’s here as a blueprint that lines up with the rest of the doc so the next dev doesn’t reinvent a totally different shape.

---

## 9. Summary for Future Devs

- **Inside the app:**
  
  - Contracts raise `app.extensions.errors.ContractError`.
  
  - Slices never see `GatewayContractRequest/Response`.

- **At the gateway edge:**
  
  - Requests/Responses use the envelope described above.
  
  - The gateway is the *only* thing that converts between “envelope” and “contract + kwargs”.

- **Error mapping is 1:1:**
  
  - `ContractError` → `GatewayError` with the same `code/where/message/http_status/data`.

If someone comes along later and wants gRPC, WebSockets, or a queue worker, this gives them a canonical mapping to follow, without dragging the old `types.py`/v1 noise back into the live codebase.
