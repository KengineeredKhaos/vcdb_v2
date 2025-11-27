# VCDB Extensions Layer

The `app/extensions` package is the **glue** between slices:

- It loads and validates **governance/auth policies** from JSON files.
- It exposes small, named **enforcers** for runtime gates.
- It defines **contracts** that slices use to talk to each other
  without reaching directly into each other's tables.

Think of it as: _“everything cross-slice that is not a DB model or a
Flask route lives here.”_

---

## 1. Policy stack

### 1.1. JSON + JSON Schema helpers

The base JSON + schema helpers live in `app/extensions/validate.py`:

- `load_json(path)`: load UTF-8 JSON from disk.
- `load_json_schema(path)`: load a JSON Schema document (must be an
  object).
- `validate_json_payload(payload, schema_path)`: validate with
  Draft 2020-12 and raise on failure. :contentReference[oaicite:0]{index=0}  

These are used by the policy loader / semantics code to keep all
policy/config validation behavior consistent.

### 1.2. Policy loader and cache

`app/extensions/policies.py`:

- Loads JSON-based policies (issuance, domain, calendar, rbac, etc.)
  from `slices/governance/data/` and `slices/auth/data/`.
- Optionally validates them against JSON Schemas (via the helpers above).
- Caches policies by mtime/hash so repeated reads are cheap.
- Provides `save_policy(...)` for Admin-only writes, including optional
  audit hooks.

Slices **never** reach into `slices/governance/data` directly; they go
through `extensions.policies`.

### 1.3. Policy semantics vs hints

- `policy_semantics.py` contains **hard rules** and cross-file checks
  (domain ↔ RBAC, issuance vs SKU catalog, cadence resolution, etc.).
- `policy_hints.py` turns those into advisory **hints** for UIs and CLI
  diagnostics (“you almost have coverage for this SKU…”, etc.).

Schemas do structure, `policy_semantics` does meaning, `policy_hints`
does UX.

---

## 2. Runtime enforcers

`app/extensions/enforcers.py` defines a small registry of named runtime
gates (e.g. `calendar_blackout_ok`).

Slices call these by name instead of reading policies directly. Example
pattern:

```python
ok, meta = enforcers["calendar_blackout_ok"](ctx)
if not ok:
    # meta.reason will say why (e.g. "calendar_blackout")
```

This gives you one vocabulary for cross-cutting checks (calendar
blackouts now, cadence/etc. later) without tangling slices together.

---

## 3. Auth context

`app/extensions/auth_ctx.py`is the adapter between:

Flask-Login’s current_user, and

VCDB’s notion of an actor ULID (the thing we put into logs and
ledger events).

Today it’s intentionally simple (mint-and-cache an actor ULID in the
session), but the contract is:

“Call current_actor_ulid() if you need to know who is acting at the
Extensions layer.”

Future refinements (mapping to Entity rows, Governance rules, etc.) live
behind that function.

---

## 4. Contracts & schemas

Cross-slice communication is done via versioned contracts under
`app/extensions/contracts/`:

- Each contract module (e.g. customers_v2, sponsors_v2) defines
  DTO-ish return shapes and raises only ContractError on failure.

- Callers never import slice models or services directly; they call a
  contract function instead.

### 4.1. Contract-level validation

For JSON-ish payloads, contracts can use
`app/extensions/contracts/validate.py`:

- `load_schema(module_file, rel_path)` loads a JSON Schema located under
  the same package (e.g. `schemas/customer.request.json)`.

- `validate_payload(schema, payload)` validates the payload with
  Draft 2020-12 and raises `ContractValidationError` on failure.

`ContractValidationError` is a specialization of `ContractError` with:

- `code="payload_invalid"`

- `where="contracts.validate.validate_payload"`

- `http_status=400`

- `data` including the failing JSON path and schema path.

This gives contracts a standard way to report payload problems
without leaking jsonschema’s exception types.

### 4.2. Where schemas live

Each contract package can ship its own JSON Schemas under a local
`schemas/` directory, for example:

- `app/extensions/contracts/customers_v2/schemas/verify.request.json`

- `app/extensions/contracts/resources_v2/schemas/capabilities.patch.json`

Pattern:

1. Call `schema = load_schema(__file__, "schemas/whatever.json")` at
   module import time or lazily.

2. In the contract function, call `validate_payload(schema, payload)`
   before touching slice services.

3. If validation fails, callers see `ContractValidationError` (which is
   just a structured `ContractError`).

---

## 5. Error model (ContractError)

All contracts ultimately raise app.extensions.errors.ContractError:

- `code`: machine-readable error code (`e.g. bad_argument`,
  `not_found`, `payload_invalid`).

- `where`: fully-qualified contract function, e.g.
  `"customers_v2.verify_veteran"`.

- `message`: human-readable explanation.

- `http_status`: what the HTTP layer would return.

- `data`: PII-free breadcrumbs (ULIDs, keys, counts, JSON paths).

`ContractValidationError` from `contracts/validate` is just a
specialized `ContractError` with a consistent shape for JSON Schema
failures.

Routes, CLI commands, and Admin UIs all just:

```python
try:
 result = customers_v2.verify_veteran(...)
except ContractError as e:
 # log e.to_dict(), render based on e.http_status / e.code, etc.
```

---

## 6. Mental model & how to add new stuff

When adding a new cross-slice feature, think in this order:

- Policy (if needed):
  
  - Add/extend a JSON policy file under slices/governance/data/.
  
  - Add/extend the JSON Schema under slices/governance/schemas/.
  
  - Wire semantic checks into policy_semantics.py.

- Enforcer (if there’s a runtime gate):
  
  - Add a small function in `enforcers.py` that reads policy and returns
    `(ok, meta)`.

- Contract:
  
  - Add a new `*_vN.py` module under `extensions/contracts` or extend
    the existing one.
  
  - For complex payloads, add JSON Schemas under `schemas/` and wire
    them through `contracts/validate.py`.
  
  - Map all failures to `ContractError` (or `ContractValidationError`).

- Slice implementation:
  
  - Call the contract from routes / services rather than reaching
    across slices.
