Here’s a compact “tape-it-to-your-monitor” cheat sheet for `ContractError` and the ledger/event_bus path.

---

## 0. Single source of truth

- **Type:** `app.extensions.errors.ContractError`

- **Specialization for JSON Schema:** `ContractValidationError(ContractError)` in `app/extensions/contracts/validate.py`

- **Canonical ledger write contract:** `app.extensions.contracts.ledger_v2.emit`

- **Public entry point for slices:** `app.extensions.event_bus.emit`

---

## 1. When to use `ContractError`

**Use `ContractError` only at contract boundaries:**

- In `app/extensions/contracts/*` (including `ledger_v2`).

- In `contracts/validate.py` (JSON Schema).

- In any thin compatibility shims that pretend to be contracts (`contracts/ledger/__init__.py`).

**Do NOT** use `ContractError` deep inside slice internals unless it’s a temporary shim (like `poc.py`).

Inside slices:

- Raise **slice-local** exceptions and let the contract map them to `ContractError`.

---

## 2. How to raise `ContractError` (canonical shape)

Always use **keyword args**, never positional:

```python
from app.extensions.errors import ContractError

where = "governance_v2.get_poc_policy"  # module.function

raise ContractError(
    code="policy_invalid",
    where=where,
    message="POC policy missing required keys",
    http_status=503,
    data={"required": ["poc_scopes", "default_scope", "max_rank"], "path": str(path)},
)
```

Template you can copy/paste:

```python
raise ContractError(
    code="...",
    where="module.func",
    message="...",
    http_status=...,
    data={...},  # optional
)
```

**Never** pass extra kwargs like `details=`, `cause=`, etc.  
If you want causal chaining, do:

```python
except SomeInternalError as e:
    raise ContractError(...) from e
```

---

## 3. `code` naming conventions

Short, snake_case, stable. Think “log filter name,” not sentence.

**Categories:**

- **Policy/config:**
  
  - `policy_missing` (required policy file not present)
  
  - `policy_invalid` (schema/semantics wrong)

- **Input/payload / caller misuse:**
  
  - `payload_invalid` (JSON Schema validation fail or required keys missing)
  
  - `bad_argument` (argument wrong type/value)
  
  - `unsupported_operation`

- **Domain semantics:**
  
  - `not_found` (thing doesn’t exist from contract POV)
  
  - `conflict` or `state_conflict` (contract-level conflict, e.g. optimistic concurrency)

- **Infrastructure / system:**
  
  - `ledger_unavailable`
  
  - `ledger_hash_conflict`
  
  - `db_unavailable`
  
  - `upstream_error`

**Rule:** `code` should be enough to know “what *class* of problem” it is without reading `message`.

---

## 4. `where` convention

Always:

```text
"<module_name>.<function_name>"
```

Examples:

- `governance_v2.get_poc_policy`

- `governance_v2.get_role_catalogs`

- `ledger_v2.emit`

- `contracts.ledger.emit_event`

- `contracts.validate.validate_payload`

**Rule:** `where` points at the public contract function, **not** random internal helpers.

---

## 5. `http_status` guidance

Think “what HTTP status would I return if this were an HTTP API?”

- **400** – structurally bad request:
  
  - Missing required keys, wrong types, bogus enums.
  
  - JSON Schema failures (`payload_invalid`).

- **404** – object not found:
  
  - `not_found` for missing ledger event, missing policy record from contract perspective.

- **409** – conflict:
  
  - Version/etag mismatch, state conflict.

- **422** – semantically invalid but structurally OK:
  
  - Fails business rules; e.g., “cannot transition from CLOSED to PENDING”.

- **5xx** – system/config:
  
  - Missing policy file, corrupt policy, DB offline, ledger provider down, hash chain conflict.

Default for “config/system” contracts (like governance + ledger) is **503**.

---

## 6. `data` payload rules

- **Never PII** (no names, emails, SSNs, etc.).

- Keep it small and machine-friendly:
  
  - IDs/ULIDs, file paths, bad field names, limits.

- Example:

```python
data={
    "path": str(path),
    "required": ["poc_scopes", "default_scope", "max_rank"],
}
```

Good patterns:

- Policy: `{"path": str(path), "missing_keys": [...]}`

- Payload: `{"path": "refs.customer_id", "schema_path": [...]}`

- Domain: `{"event_ulid": event_ulid}`

- Ledger: `{"hint": "re-read tail"}`

---

## 7. JSON Schema validation (`ContractValidationError`)

Entry point: `app/extensions/contracts/validate.py`

Usage in contracts:

```python
from app.extensions.contracts.validate import load_schema, validate_payload

schema = load_schema(__file__, "schemas/some.request.json")
validate_payload(schema, payload)  # raises ContractValidationError on failure
```

Shape:

- `code`: `"payload_invalid"`

- `where`: `"contracts.validate.validate_payload"`

- `http_status`: `400`

- `data` includes:
  
  - `"path"` – JSON dotted path to offending field.
  
  - `"schema_path"` – where in schema it failed.

Treat it like any other `ContractError` at the route layer.

---

## 8. Ledger / event bus specifics

### Call path (write):

```python
# Inside slices (services/routes):
from app.extensions import event_bus

event_bus.emit(
    domain="governance",
    operation="policy.updated",
    request_id=request_id,
    actor_ulid=actor_ulid,
    target_ulid=target_ulid,
    refs={...},
    changed={...},
    meta={...},
    happened_at_utc=now_iso8601_ms(),
)
```

- `event_bus.emit` → `ledger_v2.emit`

- `ledger_v2.emit`:
  
  - Calls `ledger.services.append_event`.
  
  - On provider failure, raises `ContractError` with:
    
    - `code="ledger_hash_conflict"` or `code="ledger_unavailable"`
    
    - `where="ledger_v2.emit"`

### Contract layer:

- **Use ledger_v2 directly in contracts** (rare outside event_bus).

- In compatibility shims (`contracts/ledger/__init__.py`), wrap calls to `ledger_v2.emit` and normalize required keys; never talk to `services` directly anymore.

---

## 9. Common patterns / examples

### A. Policy missing

```python
where = "governance_v2.get_poc_policy"

if not path.exists():
    raise ContractError(
        code="policy_missing",
        where=where,
        message="POC policy file not found",
        http_status=503,
        data={"path": str(path)},
    )
```

### B. Caller passed bad arguments

```python
where = "customers_v2.get_profile"

if tier not in ("tier1", "tier2", "tier3"):
    raise ContractError(
        code="bad_argument",
        where=where,
        message=f"unknown tier '{tier}'",
        http_status=400,
        data={"allowed": ["tier1", "tier2", "tier3"]},
    )
```

### C. Ledger conflict

```python
where = "ledger_v2.emit"

try:
    row = ledger_svc.append_event(...)
except ledger_svc.EventHashConflict as e:
    raise ContractError(
        code="ledger_hash_conflict",
        where=where,
        message="ledger hash conflict when appending event",
        http_status=503,
        data={"hint": "re-read tail"},
    ) from e
```

---

## 10. Anti-patterns to grep for (refactor when seen)

Use ripgrep (`rg`) for these:

1. **Positional ContractError calls** (no `code=`):
   
   ```bash
   rg "ContractError\(" app | rg -v "code="
   ```

2. **Old kwargs**:
   
   - `details=`
   
   - `cause=`

```bash
rg "details=" app
rg "cause=" app
```

3. **Non-qualified `where`** (e.g., `"emit"` instead of `"ledger_v2.emit"`):
   
   ```bash
   rg 'where="[^"]+"' app
   ```

---

If you want, next step I can draft a **tiny “ContractError cookbook” section** for your scaffolding_docs (with 3–4 full before/after snippets), but this should be enough as your day-to-day reference while you sweep.
