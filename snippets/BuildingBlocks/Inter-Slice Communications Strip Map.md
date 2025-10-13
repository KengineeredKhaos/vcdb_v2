# Table of Contents

* Table of Contents
  - [Strip Map](#strip-map)
  - [The Contracts](#the-contracts)
  - [Minimal Skeletons](#minimal-skeletons)
  - [Service Stub Examples](#service-stub-examples)

# Strip Map

A clean, contract-first flow in plain language, mapped to the moving parts (no code, just roles).

## End-to-end request/response (happy path)

1. User hits a route in
   
   - **Who:** `<slice1>.routes`
   
   - **What:** Collects inputs (form/URL/json), does quick UX checks, and hands them to services.

2. prepares a contract request DTO
   
   - **Who:** `<slice1>.services`
   
   - **What:** Builds a **contract request DTO** (the shape defined by `extensions/contracts/<slice2>/v1/...`) — not an internal DB model. Adds `request_id`, `actor_id` (if applicable), and timestamps.

3. calls the contract facade
   
   - **Who:** `extensions/contracts/<slice2>/v1`
   
   - **What:** Validates the payload against the **request JSON Schema**. If invalid, raises `ContractValidationError` (clean, user-safe message).
   
   - **Then:** Delegates to the provider slice’s service layer.

4. executes business/data work
   
   - **Who:** `<slice2>.services`
   
   - **What:** Enforces rules and permissions, hits its own DB tables, composes results. If it logs to the ledger, it emits a ledger contract call here. Returns a **provider response DTO** (plain dict).

5. Contract validates the response
   
   - **Who:** `extensions/contracts/<slice2>/v1`
   
   - **What:** Validates the returned dict against the **response JSON Schema**.
     
     - If provider says “not found”, map to `ContractDataNotFound`.
     
     - If hash/lock conflicts, map to `ContractConflict`.
     
     - If dependency is down, map to `ContractUnavailable`.

6. consumes the response DTO
   
   - **Who:** `<slice1>.services`
   
   - **What:** Interprets the response DTO, maybe adapts it to ’s local view models or template context.

7. Render to user
   
   - **Who:** `<slice1>.routes`
   
   - **What:** Returns a template or JSON to the client.

## Error paths (how they propagate)

- **Bad input at the boundary:** Contract raises `ContractValidationError` (points to the JSON path of the problem); route turns this into a 400 with a friendly message.

- **Missing data upstream:** Contract raises `ContractDataNotFound`; route chooses 404 or a “no results” page.

- **Write conflicts / hash mismatch:** Contract raises `ContractConflict`; route can suggest retry/reload.

- **Provider down:** Contract raises `ContractUnavailable`; route shows a “try again later”.

## What’s important to keep straight

- **DTO vs. DB model:**  
  DTOs are the **wire format** for contracts (schema-checked). DB models never cross slice boundaries.

- **Contracts are the only tunnel:**  
  never imports `<slice2>.services` directly. Everything goes through `extensions/contracts/<slice2>/v1`.

- **Validation on both sides:**  
  Contract validates **requests** before calling the provider, and **responses** before returning to the caller. That’s your consistency firewall.

- **IDs & time:**  
  Include `request_id` (ULID), `actor_id` (entity/account ULID), and a UTC ISO 8601 timestamp in the request DTO when it matters (for audit/ledger correlation). Providers add their own `event_ulid` etc. when they write.

- **Ledger hooks:**  
  When a slice changes state, it should emit a **ledger contract** call inside step 4. That contract validates the ledger DTO and appends the event (hash chain, etc.).

That’s the map. Next we take one concrete use case (e.g., “Admin adjusts roles”) and sketch the exact fields in each DTO at each hop to cement it.

---

# The Contracts

## Admin adjusts roles:

 (add/remove system & domain roles on an entity), with **dry-run** and **commit** and **ledger emission** showing the DTOs, the contract shapes, and where validation happens.

---

## 0) Preconditions (where data lives)

- **Governance slice** owns **policy roles** (the *allowed* domain roles, e.g., `customer`, `resource`, `sponsor`, `governor`…). Exposed via **governance contract v1** (read-only).

- **Auth slice** owns **RBAC roles** (e.g., `user`, `auditor`, `admin`). Exposed via **auth contract v1** (read-only for picklists; writes happen through admin op, not directly).

- **Admin slice** owns **the role-adjust operation** (this is the write path). Exposed via **admin contract v1**.

---

## 1) Caller → Contract (Admin contract v1)

### Request DTO (admin.adjust_roles.request)

Used by `<slice1>.services` (Admin routes’ service) to call the **Admin contract**:

```json
{
  "request_id": "01J9M8R2W2J9B8K2FKWQG2X0WZ",
  "actor_id": "01J9M8QYV9E2BKHX5Q9F4S6D3R",   // the account/entity performing the change
  "happened_at": "2025-10-06T17:02:03Z",
  "dry_run": true,
  "target": {
    "entity_ulid": "01J8Z4BYR6J6S8M9V5JM2D4X3A"
  },
  "desired": {
    "domain_roles_add":    ["customer"],
    "domain_roles_remove": ["sponsor"],
    "rbac_roles_add":      ["auditor"],
    "rbac_roles_remove":   []
  },
  "note": "Fixing onboarding mistake; removing sponsor, adding customer + auditor"
}
```

**Contract request schema (high-level):**

- `request_id`, `actor_id`, `happened_at` → required ISO-8601Z + ULIDs.

- `dry_run` boolean required.

- `desired.*` arrays are string lists; **must be unique**; may be empty.

- **No unknown keys**.

**Contract validates**:

- Shape/types (JSON Schema).

- **Allowed values**: it calls
  
  - `governance.v1.list_allowed_domain_roles()` for `domain_roles_*`
  
  - `auth.v1.list_allowed_rbac_roles()` for `rbac_roles_*`

- Fails fast with `ContractValidationError` if any value isn’t allowed.

---

## 2) Contract → Admin services (provider slice)

**Admin services** loads current state and computes a diff.

### Provider computes:

- Current roles (from entity/auth tables via its own data):
  
  ```json
  {
    "current": {
      "domain_roles": ["sponsor"],
      "rbac_roles": ["user"]
    }
  }
  ```

- **Resulting** (post-change) sets and **delta**:
  
  ```json
  {
    "resulting": {
      "domain_roles": ["customer"],  // sponsor removed, customer added
      "rbac_roles": ["user", "auditor"]
    },
    "delta": {
      "added":   { "domain_roles": ["customer"], "rbac_roles": ["auditor"] },
      "removed": { "domain_roles": ["sponsor"],  "rbac_roles": [] }
    }
  }
  ```

- **Conflicts** (if any): e.g., trying to remove a role that isn’t present, or add a duplicate → these are **benign** (no-op) unless policy forbids; then they go to `warnings` or `errors`.

- **Dry-run**:
  
  - If `dry_run: true`: **no DB writes**, **no ledger event**; just return a preview with `commit_possible: true/false`.

- **Commit**:
  
  - If `dry_run: false`: apply DB updates inside a transaction, then **emit a ledger event** via the **ledger contract**.

---

## 3) Admin contract → Caller (Admin routes’ service)

### Response DTO (admin.adjust_roles.response)

```json
{
  "request_id": "01J9M8R2W2J9B8K2FKWQG2X0WZ",
  "target": {
    "entity_ulid": "01J8Z4BYR6J6S8M9V5JM2D4X3A"
  },
  "dry_run": true,
  "current": {
    "domain_roles": ["sponsor"],
    "rbac_roles": ["user"]
  },
  "resulting": {
    "domain_roles": ["customer"],
    "rbac_roles": ["user", "auditor"]
  },
  "delta": {
    "added":   { "domain_roles": ["customer"], "rbac_roles": ["auditor"] },
    "removed": { "domain_roles": ["sponsor"],  "rbac_roles": [] }
  },
  "warnings": [],
  "commit_possible": true
}
```

**Contract validates** this against the **response JSON Schema** (no slice-internal types leak out).  
If commit happened, add:

```json
"ledger": {
  "event_ulid": "01J9M8T3C3J9F2V7D4K2S1N8QP",
  "event_hash": "f24c8c5a...",
  "happened_at": "2025-10-06T17:02:04Z",
  "correlation_id": "01J9M8R2W2J9B8K2FKWQG2X0WZ"
}
```

---

## 4) Ledger emission (inside Admin services when commit = true)

**Ledger DTO (ledger.append_event.request)** (generic we can reuse):

```json
{
  "event_ulid": "01J9M8T3C3J9F2V7D4K2S1N8QP",
  "happened_at": "2025-10-06T17:02:04Z",
  "domain": "admin",
  "type": "role_adjustment",
  "operation": "update",
  "actor_id": "01J9M8QYV9E2BKHX5Q9F4S6D3R",
  "target_id": "01J8Z4BYR6J6S8M9V5JM2D4X3A",
  "request_id": "01J9M8R2W2J9B8K2FKWQG2X0WZ",
  "correlation_id": "01J9M8R2W2J9B8K2FKWQG2X0WZ",
  "changed_fields_json": {
    "domain_roles": {
      "before": ["sponsor"],
      "after":  ["customer"]
    },
    "rbac_roles": {
      "before": ["user"],
      "after":  ["user", "auditor"]
    },
    "note": "Fixing onboarding mistake; removing sponsor, adding customer + auditor"
  },
  "refs_json": {
    "policy_snapshot": {
      "allowed_domain_roles": ["customer","resource","sponsor","governor"],
      "allowed_rbac_roles":   ["user","auditor","admin"]
    }
  },
  "prev_event_id": "01J9M8QW8E5WQ0R2Y6H1F9A4TN",
  "prev_hash": "7aee1b8e...",
  "event_hash": "f24c8c5a..."        // computed by ledger slice
}
```

**Ledger contract** validates & writes; returns its **event_ulid + event_hash**, which Admin contract includes in its response (see above).

---

## 5) Typical UI flow

- **GET**: Admin / “Adjust roles” page
  
  - Calls `governance.v1.list_allowed_domain_roles()` and `auth.v1.list_allowed_rbac_roles()` to populate dropdowns.

- **POST (Dry Run)**:
  
  - Builds **request DTO** with `dry_run:true`, calls `admin.v1.adjust_roles`.
  
  - Shows side-by-side “Current vs Resulting”, warns about any conflicts.
  
  - If `commit_possible:true`, show **Commit** button.

- **POST (Commit)**:
  
  - Same request but `dry_run:false`.
  
  - On success, flash “Roles updated” plus a short ledger reference (event ULID).

---

## 6) Error mapping (clean boundaries)

- Invalid values (not in governance/auth lists) → **`ContractValidationError`** (400).

- Target not found → **`ContractDataNotFound`** (404).

- Concurrent write conflict (ETag / version) → **`ContractConflict`** (409).

- Provider down → **`ContractUnavailable`** (503).

- Anything else → log internally, surface a generic **`ContractError`** (500-ish), without leaking internals.

---

## 7) Why this stays DRY and safe

- **No direct cross-slice imports**: Admin only hits Governance/Auth via contracts for *allowed lists*; it performs the write and ledger emission itself.

- **Schemas** make both sides explicit; they’re reusable for UI (enums) and tests (golden DTOs).

- **Dry-run** is the same call with a flag—no separate logic branches or extra endpoints.

- **Ledger** is a *separate* contract call from Admin services, keeping the audit trail centralized and consistent.

---

# Minimal Skeletons for:

- `governance.v1.list_allowed_domain_roles()` request/response schemas,

- `auth.v1.list_allowed_rbac_roles()` request/response schemas,

- `admin.v1.adjust_roles()` request/response schemas,

- `ledger.v1.append_event()` request schema,



Here are **copy-pasteable skeletons** for the four contracts. They’re intentionally small, DRY, and aligned with what we discussed: JSON Schemas at the boundary, thin facades that call into slice services, and clear, contract-layer errors.

---

## app/extensions/contracts/errors.py

```python
# app/extensions/contracts/errors.py

class ContractError(RuntimeError):
    """Base class for contract-layer errors (surface these to callers)."""
    pass

class ContractValidationError(ContractError):
    """Payload failed contract schema validation."""
    pass

class ContractDataNotFound(ContractError):
    """The requested data was not found in the provider slice."""
    pass

class ContractConflict(ContractError):
    """Concurrency/version conflict (e.g., optimistic lock)."""
    pass

class ContractUnavailable(ContractError):
    """Provider slice temporarily unavailable or dependency failed."""
    pass
```

---

## Tiny helper (optional)

```python
# app/extensions/contracts/_schema.py
from jsonschema import Draft202012Validator
from .errors import ContractValidationError

def validate(schema: dict, payload: dict) -> None:
    try:
        Draft202012Validator(schema).validate(payload)
    except Exception as e:
        raise ContractValidationError(str(e)) from e
```

---

## 1) Governance v1 – list_allowed_domain_roles (READ)

```python
# app/extensions/contracts/governance/v1.py
from typing import Dict, List
from app.slices.governance import services as gov_services
from ..errors import ContractDataNotFound
from .._schema import validate

# ---- Response Schema (roles list) ----
LIST_ALLOWED_DOMAIN_ROLES_RESP = {
    "type": "object",
    "required": ["roles", "as_of"],
    "additionalProperties": False,
    "properties": {
        "roles": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "as_of": {"type": "string", "format": "date-time"},
    },
}

def list_allowed_domain_roles() -> Dict:
    """
    Facade for 'what domain roles are currently allowed?' (customer, resource, sponsor, governor, ...)
    """
    roles: List[str] = gov_services.policy_get_roles_list()  # you already have this
    if roles is None:
        raise ContractDataNotFound("No domain roles policy found.")
    resp = {"roles": roles, "as_of": gov_services.policy_timestamp_iso()}
    validate(LIST_ALLOWED_DOMAIN_ROLES_RESP, resp)
    return resp
```

---

## 2) Auth v1 – list_allowed_rbac_roles (READ)

```python
# app/extensions/contracts/auth/v1.py
from typing import Dict, List
from app.slices.auth import services as auth_services
from ..errors import ContractDataNotFound
from .._schema import validate

# ---- Response Schema (rbac roles list) ----
LIST_ALLOWED_RBAC_ROLES_RESP = {
    "type": "object",
    "required": ["roles", "as_of"],
    "additionalProperties": False,
    "properties": {
        "roles": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "as_of": {"type": "string", "format": "date-time"},
    },
}

def list_allowed_rbac_roles() -> Dict:
    """
    Facade for RBAC role names (user, auditor, admin, ...)
    """
    roles: List[str] = auth_services.list_rbac_roles_allowed()
    if not roles:
        raise ContractDataNotFound("No RBAC roles are defined.")
    resp = {"roles": roles, "as_of": auth_services.roles_timestamp_iso()}
    validate(LIST_ALLOWED_RBAC_ROLES_RESP, resp)
    return resp
```

---

## 3) Admin v1 – adjust_roles (WRITE with dry-run/commit + ledger)

```python
# app/extensions/contracts/admin/v1.py
from typing import Dict, List
from app.slices.admin import services as admin_services
from app.extensions.contracts.governance.v1 import list_allowed_domain_roles
from app.extensions.contracts.auth.v1 import list_allowed_rbac_roles
from ..errors import ContractDataNotFound, ContractConflict
from .._schema import validate

# ---- Request Schema ----
ADJUST_ROLES_REQ = {
    "type": "object",
    "required": ["request_id", "actor_id", "happened_at", "dry_run", "target", "desired"],
    "additionalProperties": False,
    "properties": {
        "request_id": {"type": "string", "minLength": 10},
        "actor_id": {"type": "string", "minLength": 10},
        "happened_at": {"type": "string", "format": "date-time"},
        "dry_run": {"type": "boolean"},
        "target": {
            "type": "object",
            "required": ["entity_ulid"],
            "additionalProperties": False,
            "properties": {"entity_ulid": {"type": "string", "minLength": 10}},
        },
        "desired": {
            "type": "object",
            "required": ["domain_roles_add","domain_roles_remove","rbac_roles_add","rbac_roles_remove"],
            "additionalProperties": False,
            "properties": {
                "domain_roles_add":    {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
                "domain_roles_remove": {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
                "rbac_roles_add":      {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
                "rbac_roles_remove":   {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
            },
        },
        "note": {"type": "string"},
    },
}

# ---- Response Schema ----
ADJUST_ROLES_RESP = {
    "type": "object",
    "required": ["request_id", "target", "dry_run", "current", "resulting", "delta", "warnings", "commit_possible"],
    "additionalProperties": False,
    "properties": {
        "request_id": {"type": "string"},
        "target": {
            "type": "object",
            "required": ["entity_ulid"],
            "additionalProperties": False,
            "properties": {"entity_ulid": {"type":"string"}},
        },
        "dry_run": {"type": "boolean"},
        "current": {
            "type": "object",
            "required": ["domain_roles","rbac_roles"],
            "additionalProperties": False,
            "properties": {
                "domain_roles": {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
                "rbac_roles":   {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
            },
        },
        "resulting": {
            "type": "object",
            "required": ["domain_roles","rbac_roles"],
            "additionalProperties": False,
            "properties": {
                "domain_roles": {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
                "rbac_roles":   {"type": "array", "items": {"type":"string"}, "uniqueItems": True},
            },
        },
        "delta": {
            "type": "object",
            "required": ["added","removed"],
            "additionalProperties": False,
            "properties": {
                "added": {
                    "type":"object",
                    "required":["domain_roles","rbac_roles"],
                    "additionalProperties": False,
                    "properties": {
                        "domain_roles": {"type": "array","items":{"type":"string"},"uniqueItems": True},
                        "rbac_roles":   {"type": "array","items":{"type":"string"},"uniqueItems": True},
                    },
                },
                "removed": {
                    "type":"object",
                    "required":["domain_roles","rbac_roles"],
                    "additionalProperties": False,
                    "properties": {
                        "domain_roles": {"type": "array","items":{"type":"string"},"uniqueItems": True},
                        "rbac_roles":   {"type": "array","items":{"type":"string"},"uniqueItems": True},
                    },
                },
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
        "commit_possible": {"type": "boolean"},
        "ledger": {
            "type": "object",
            "required": ["event_ulid","event_hash","happened_at","correlation_id"],
            "additionalProperties": False,
            "properties": {
                "event_ulid": {"type":"string"},
                "event_hash": {"type":"string"},
                "happened_at":{"type":"string","format":"date-time"},
                "correlation_id":{"type":"string"},
            },
        },
    },
}

def adjust_roles(req: Dict) -> Dict:
    """
    Add/remove domain & RBAC roles on a target entity.
    - Validates against governance/auth allowed lists.
    - dry_run=True: no DB writes, no ledger.
    - dry_run=False: apply & emit ledger event.
    """
    validate(ADJUST_ROLES_REQ, req)

    # 1) Fetch allowed lists for validation
    allowed_domain = set(list_allowed_domain_roles()["roles"])
    allowed_rbac   = set(list_allowed_rbac_roles()["roles"])

    desired = req["desired"]
    for key in ("domain_roles_add","domain_roles_remove"):
        illegal = [r for r in desired[key] if r not in allowed_domain]
        if illegal:
            from ..errors import ContractValidationError
            raise ContractValidationError(f"Illegal domain roles in '{key}': {illegal}")
    for key in ("rbac_roles_add","rbac_roles_remove"):
        illegal = [r for r in desired[key] if r not in allowed_rbac]
        if illegal:
            from ..errors import ContractValidationError
            raise ContractValidationError(f"Illegal RBAC roles in '{key}': {illegal}")

    # 2) Delegate to provider slice service
    try:
        result: Dict = admin_services.adjust_roles_apply_or_preview(req)
        # Expected to return a dict matching ADJUST_ROLES_RESP (if commit, includes 'ledger' block)
    except admin_services.NotFoundError:
        raise ContractDataNotFound("Entity not found.")
    except admin_services.ConflictError:
        raise ContractConflict("Concurrent modification detected.")

    validate(ADJUST_ROLES_RESP, result)
    return result
```

> The **actual DB logic** (read current roles, compute diff, dry-run/commit, call ledger contract on commit) lives in `app/slices/admin/services.adjust_roles_apply_or_preview`.

---

## 4) Ledger v1 – append_event (WRITE)

```python
# app/extensions/contracts/ledger/v1.py
from typing import Dict
from app.slices.ledger import services as ledger_services
from ..errors import ContractValidationError
from .._schema import validate

APPEND_EVENT_REQ = {
    "type": "object",
    "required": ["event_ulid","happened_at","domain","type","operation","actor_id","target_id","request_id","correlation_id","changed_fields_json","refs_json"],
    "additionalProperties": False,
    "properties": {
        "event_ulid": {"type":"string"},
        "happened_at": {"type":"string","format":"date-time"},
        "domain": {"type":"string","minLength":1},
        "type": {"type":"string","minLength":1},
        "operation": {"type":"string","minLength":1},
        "actor_id": {"type":"string","minLength":10},
        "target_id": {"type":"string","minLength":10},
        "request_id": {"type":"string","minLength":10},
        "correlation_id": {"type":"string","minLength":10},
        "changed_fields_json": {"type":"object"},
        "refs_json": {"type":"object"},
        "prev_event_id": {"type":"string"},
        "prev_hash": {"type":"string"},
    },
}

APPEND_EVENT_RESP = {
    "type": "object",
    "required": ["event_ulid","event_hash","happened_at"],
    "additionalProperties": False,
    "properties": {
        "event_ulid": {"type":"string"},
        "event_hash": {"type":"string"},
        "happened_at":{"type":"string","format":"date-time"},
    },
}

def append_event(payload: Dict) -> Dict:
    """
    Append a single immutable ledger event; returns (event_ulid, event_hash, happened_at).
    Hashing/linking handled by the ledger slice.
    """
    validate(APPEND_EVENT_REQ, payload)

    # Optional: lightweight contract-level constraints:
    if payload["domain"] not in {"admin","entity","customer","resource","sponsor","governance","auth","transactions"}:
        raise ContractValidationError("Unknown ledger domain.")
    if payload["operation"] not in {"create","update","delete","repair","noop"}:
        raise ContractValidationError("Unknown operation.")

    resp = ledger_services.append_event(payload)  # dict with keys matching APPEND_EVENT_RESP
    validate(APPEND_EVENT_RESP, resp)
    return resp
```

---

## How to wire this (one-liners you can call from routes/services)

- From **Admin routes service**:
  
  - Get picklists for dropdowns:
    
    ```python
    from app.extensions.contracts.governance.v1 import list_allowed_domain_roles
    from app.extensions.contracts.auth.v1 import list_allowed_rbac_roles
    
    allowed_domain = list_allowed_domain_roles()["roles"]
    allowed_rbac   = list_allowed_rbac_roles()["roles"]
    ```
  
  - Dry-run / Commit:
    
    ```python
    from app.extensions.contracts.admin.v1 import adjust_roles
    preview = adjust_roles(req_dict)  # dry_run=True or False
    ```

- Inside **Admin services** (when committing), emit ledger:
  
  ```python
  from app.extensions.contracts.ledger.v1 import append_event
  ledger_resp = append_event(event_payload_dict)
  ```

That’s it—clean boundaries, schemas at the edges, fat services inside each slice.

---

# Service Stub Examples

These are **minimal, copy-pasteable service stubs** that the contracts above will call. They’re intentionally tiny, DB-agnostic (use TODOs where SQLAlchemy will be wired in), and they return payloads that **conform to the schemas** defined in the contracts.

---

## app/slices/governance/services.py

```python
# app/slices/governance/services.py
"""
Governance services (READ).
Provides policy-backed domain roles and a timestamp for cache-busting.
"""

from typing import List
from app.lib import utc_now  # assumes you expose this in app/lib/__init__.py

# TODO: replace with real DB-backed policy fetch
_DOMAIN_ROLES_CACHE = ["customer", "resource", "sponsor", "governor"]

def policy_get_roles_list() -> List[str]:
    """
    Return *domain* roles allowed by Governance policy.
    (These are NOT RBAC roles.)
    """
    # TODO: query your governance.policy table -> JSON policy['roles']
    return list(_DOMAIN_ROLES_CACHE)

def policy_timestamp_iso() -> str:
    """
    Returns an ISO-8601 timestamp indicating 'as of' for the roles policy.
    Use the policy row's updated_at in the real implementation.
    """
    return utc_now()
```

---

## app/slices/auth/services.py

```python
# app/slices/auth/services.py
"""
Auth services (READ).
Provides allowed RBAC roles and timestamp.
"""

from typing import List
from app.lib import utc_now  # expose via lib public API

# TODO: replace with DB table "rbac_role" read
_RBAC_ROLES_CACHE = ["user", "auditor", "admin"]

def list_rbac_roles_allowed() -> List[str]:
    """
    Return RBAC role names that are valid.
    """
    # TODO: SELECT name FROM rbac_role WHERE is_active = 1 ORDER BY name;
    return list(_RBAC_ROLES_CACHE)

def roles_timestamp_iso() -> str:
    """
    Timestamp of the RBAC role catalog (for cache-busting).
    """
    return utc_now()
```

---

## app/slices/admin/services.py

```python
# app/slices/admin/services.py
"""
Admin services (WRITE).
Implements the role adjustment flow used by the admin contract.

- Reads an entity's current domain & RBAC roles.
- Computes the delta against 'desired'.
- If dry_run=False, applies changes (DB) and emits a ledger event.
"""

from __future__ import annotations
from typing import Dict, List, Tuple
from dataclasses import dataclass
from app.lib import utc_now, new_ulid  # your helpers

# --- Service-layer exceptions the contract may translate ---
class NotFoundError(RuntimeError):
    pass

class ConflictError(RuntimeError):
    pass


# ----------------- helpers (replace with real DB) -----------------
@dataclass
class EntityRecord:
    entity_ulid: str
    domain_roles: List[str]
    rbac_roles: List[str]
    version: int  # optimistic lock example

# pretend "database"
_DB_ENTITIES: dict[str, EntityRecord] = {}


def _load_entity(entity_ulid: str) -> EntityRecord:
    rec = _DB_ENTITIES.get(entity_ulid)
    if not rec:
        raise NotFoundError(f"Entity {entity_ulid} not found.")
    return rec

def _save_entity(rec: EntityRecord) -> None:
    # TODO: perform optimistic lock if you persist 'version'
    rec.version += 1
    _DB_ENTITIES[rec.entity_ulid] = rec


def _compute_resulting(
    current_domain: List[str],
    current_rbac: List[str],
    desired: Dict[str, List[str]],
) -> Tuple[List[str], List[str], Dict]:
    # compute domain
    dom_set = set(current_domain)
    dom_added = set(desired["domain_roles_add"])
    dom_removed = set(desired["domain_roles_remove"])
    resulting_domain = sorted((dom_set | dom_added) - dom_removed)

    # compute rbac
    rbac_set = set(current_rbac)
    rbac_added = set(desired["rbac_roles_add"])
    rbac_removed = set(desired["rbac_roles_remove"])
    resulting_rbac = sorted((rbac_set | rbac_added) - rbac_removed)

    delta = {
        "added": {
            "domain_roles": sorted(list(dom_added - dom_set)),
            "rbac_roles":   sorted(list(rbac_added - rbac_set)),
        },
        "removed": {
            "domain_roles": sorted(list(dom_removed & dom_set)),
            "rbac_roles":   sorted(list(rbac_removed & rbac_set)),
        },
    }
    return resulting_domain, resulting_rbac, delta


# ----------------- public entrypoint used by contract -----------------
def adjust_roles_apply_or_preview(req: Dict) -> Dict:
    """
    Input (validated by contract):
      {
        request_id, actor_id, happened_at, dry_run: bool,
        target: { entity_ulid },
        desired: {
          domain_roles_add/remove: [str],
          rbac_roles_add/remove:   [str]
        },
        note?: str
      }

    Returns dict matching ADJUST_ROLES_RESP schema.
    """
    entity_ulid = req["target"]["entity_ulid"]
    dry_run = req["dry_run"]

    # 1) load current
    rec = _load_entity(entity_ulid)

    # 2) compute proposed outcome
    resulting_domain, resulting_rbac, delta = _compute_resulting(
        rec.domain_roles, rec.rbac_roles, req["desired"]
    )

    warnings: List[str] = []
    # e.g., warn about becoming "governor" without "user" RBAC, etc.
    # TODO: add any business rules and append human-readable warnings.

    commit_possible = True  # flip to False if warnings must block commit

    # 3) apply on commit
    ledger_block = {
        "event_ulid": new_ulid(),
        "event_hash": "",               # filled by ledger
        "happened_at": utc_now(),
        "correlation_id": req["request_id"],
    }
    if not dry_run and commit_possible:
        # TODO: persist changes (SQLAlchemy)
        rec.domain_roles = resulting_domain
        rec.rbac_roles = resulting_rbac
        _save_entity(rec)

        # 4) emit ledger
        from app.extensions.contracts.ledger.v1 import append_event
        changed_fields = {
            "domain_roles": {"from": rec.domain_roles, "to": resulting_domain},
            "rbac_roles":   {"from": rec.rbac_roles,   "to": resulting_rbac},
        }
        payload = {
            "event_ulid": ledger_block["event_ulid"],
            "happened_at": req["happened_at"],  # use the caller’s time for traceability
            "domain": "admin",
            "type": "role.adjustment",
            "operation": "update",
            "actor_id": req["actor_id"],
            "target_id": entity_ulid,
            "request_id": req["request_id"],
            "correlation_id": req["request_id"],
            "changed_fields_json": changed_fields,
            "refs_json": {"note": req.get("note", "")},
            # optional link fields; real impl will fill prev_* in ledger slice
            "prev_event_id": "",
            "prev_hash": "",
        }
        ledger_resp = append_event(payload)
        ledger_block.update(ledger_resp)

    resp = {
        "request_id": req["request_id"],
        "target": {"entity_ulid": entity_ulid},
        "dry_run": dry_run,
        "current": {
            "domain_roles": rec.domain_roles,
            "rbac_roles": rec.rbac_roles,
        },
        "resulting": {
            "domain_roles": resulting_domain,
            "rbac_roles": resulting_rbac,
        },
        "delta": delta,
        "warnings": warnings,
        "commit_possible": commit_possible,
        "ledger": ledger_block,
    }
    return resp
```

> 📝 Notes  
> • Replace the in-memory `_DB_ENTITIES` with your actual models and queries.  
> • If you use optimistic locking, include a `version`/`updated_at` check and raise `ConflictError` on mismatch.  
> • The **contract** has already validated role names against Governance/Auth lists—do not duplicate that here; only do business-rule checks.

---

## app/slices/ledger/services.py

```python
# app/slices/ledger/services.py
"""
Ledger services (WRITE).
Appends immutable events and returns (event_ulid, event_hash, happened_at).
"""

from __future__ import annotations
import json
import hashlib
from typing import Dict
from app.lib import utc_now  # your helper

# TODO: replace with real persistent storage
_LEDGER: list[Dict] = []
_LAST_HASH = ""

def _hash_event(payload: Dict, prev_hash: str) -> str:
    # Deterministic JSON for hashing
    body = {
        "prev_hash": prev_hash,
        "payload": payload,
    }
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()

def append_event(payload: Dict) -> Dict:
    """
    Contract ensures payload schema. We:
      - link to previous event
      - compute content hash
      - persist append-only
      - return (event_ulid, event_hash, happened_at)
    """
    global _LAST_HASH

    prev_hash = _LAST_HASH
    event_hash = _hash_event(payload, prev_hash)
    happened_at = payload.get("happened_at") or utc_now()

    event_row = {
        "event_ulid": payload["event_ulid"],
        "event_hash": event_hash,
        "happened_at": happened_at,
        "prev_hash": prev_hash,
        "domain": payload["domain"],
        "type": payload["type"],
        "operation": payload["operation"],
        "actor_id": payload["actor_id"],
        "target_id": payload["target_id"],
        "request_id": payload["request_id"],
        "correlation_id": payload["correlation_id"],
        "changed_fields_json": payload["changed_fields_json"],
        "refs_json": payload["refs_json"],
    }

    # TODO: INSERT into ledger table (append-only)
    _LEDGER.append(event_row)
    _LAST_HASH = event_hash

    return {
        "event_ulid": event_row["event_ulid"],
        "event_hash": event_row["event_hash"],
        "happened_at": event_row["happened_at"],
    }
```

---

## How these stubs line up with your contracts

- `governance.services.policy_get_roles_list()` and `policy_timestamp_iso()` → used by `extensions/contracts/governance/v1.list_allowed_domain_roles()`.

- `auth.services.list_rbac_roles_allowed()` and `roles_timestamp_iso()` → used by `extensions/contracts/auth/v1.list_allowed_rbac_roles()`.

- `admin.services.adjust_roles_apply_or_preview(req)` → used by `extensions/contracts/admin/v1.adjust_roles()`.
  
  - On commit, it calls `extensions/contracts/ledger/v1.append_event()` (so ledger is centralized and consistent).

- `ledger.services.append_event(payload)` → used by `extensions/contracts/ledger/v1.append_event()`.

From here, you can replace the stubbed in-memory bits with your SQLAlchemy queries/models one function at a time, while your **contracts stay stable** and your routes/controllers remain thin.




