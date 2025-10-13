# Request/Response Cycle

Here are the building blocks so you can “see” the parts working together.

## 1) File layout (minimal)

```
app/
  extensions/
    contracts/
      governance/
        v1/
          __init__.py          # the facade
          schemas/
            policy.request.json
            policy.response.json
      validate.py              # tiny schema loader/validator
      errors.py                # contract-layer exceptions
```

## 2) `schemas/policy.request.json`

Use this when a consumer proposes a change (e.g., Admin saving allowed roles).
It enforces structure, required fields, and enum values.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "policy.request.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["key", "value", "request_id", "actor_ulid"],
  "properties": {
    "key": {
      "type": "string",
      "minLength": 1
    },
    "value": {
      "type": "object",
      "additionalProperties": false,
      "required": ["roles"],
      "properties": {
        "roles": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": [
              "customer",
              "resource",
              "sponsor",
              "governor"
            ]
          },
          "minItems": 1,
          "uniqueItems": true
        }
      }
    },
    "request_id": {
      "type": "string",
      "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$"
    },
    "actor_ulid": {
      "type": "string",
      "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$"
    },
    "comment": {
      "type": "string"
    }
  }
}
```

> Tip: the `enum` above is just a placeholder—generate it from Governance
> policy if you want dynamic enums.

## 3) `schemas/policy.response.json`

Use this for the provider’s response (what the facade returns to callers).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "policy.response.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["key", "value", "updated_at"],
  "properties": {
    "key": {
      "type": "string",
      "minLength": 1
    },
    "value": {
      "type": "object",
      "additionalProperties": false,
      "required": ["roles"],
      "properties": {
        "roles": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1,
          "uniqueItems": true
        }
      }
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "version": {
      "type": "integer",
      "minimum": 1
    }
  }
}
```

## 4) `extensions/contracts/validate.py`

A tiny, cachey loader + validator. Keep it small and boring.

```python
# app/extensions/contracts/validate.py
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator, ValidationError

from .errors import ContractValidationError

@lru_cache(maxsize=64)
def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")

@lru_cache(maxsize=64)
def load_schema(anchor_file: str, rel_path: str) -> Dict[str, Any]:
    """
    Load a JSON Schema file located relative to `anchor_file` (usually __file__ in a facade).
    Caches by absolute path.
    """
    base = Path(anchor_file).parent
    full = (base / rel_path).resolve()
    import json
    return json.loads(_read_text(str(full)))

def validate_payload(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    try:
        Draft202012Validator(schema).validate(payload)
    except ValidationError as e:
        # Normalize message; callers shouldn’t need jsonschema types
        raise ContractValidationError(e.message)
```

## 5) `extensions/contracts/errors.py`

Contract-scope exceptions (surface these to callers; keep slice/service errors behind the facade).

```python
# app/extensions/contracts/errors.py
class ContractError(RuntimeError):
    """Base class for contract-layer errors."""
    pass

class ContractDataNotFound(ContractError):
    """The requested data was not found in the provider slice."""
    pass

class ContractValidationError(ContractError):
    """Payload failed contract schema validation."""
    pass
```

## 6) `extensions/contracts/governance/v1/__init__.py` (facade)

This is the “tunnel” Admin (and others) use. It validates both the request and the provider’s response.

```python
# app/extensions/contracts/governance/v1/__init__.py
from typing import Dict, Any

from app.extensions.contracts.validate import load_schema, validate_payload
from app.extensions.contracts.errors import ContractDataNotFound
from app.slices.governance import services as gov  # provider slice

def get_policy(*, key: str) -> Dict[str, Any]:
    data = gov.policy_get(key)  # -> dict | None
    if not data:
        raise ContractDataNotFound(f"policy '{key}' not found")
    resp_schema = load_schema(__file__, "schemas/policy.response.json")
    validate_payload(data, resp_schema)
    return data

def set_policy(*, payload: Dict[str, Any]) -> Dict[str, Any]:
    req_schema = load_schema(__file__, "schemas/policy.request.json")
    validate_payload(payload, req_schema)

    out = gov.policy_set(payload)  # does DB write + emits ledger event
    resp_schema = load_schema(__file__, "schemas/policy.response.json")
    validate_payload(out, resp_schema)
    return out
```

## 7) Provider slice expectations (Governance)

Your existing `app/slices/governance/services.py` should:

- `policy_get(key) -> dict | None` (shape must match `policy.response.json`)

- `policy_set(payload) -> dict` (also matches `policy.response.json`)

- do the DB write + emit the ledger event (domain=`governance`, operation=`policy.update`, etc.)

- return `updated_at` as ISO-8601 Zulu (`to_iso8601(utc_now())`)

---

# Ledger Entry Cycle

Here’s a tiny, reusable “ledger v1” contract you can drop in. It keeps the core strict and everything else flexible, and it mirrors the ULID + ISO-8601/Zulu conventions we pinned.

## 1) File layout

```
app/
  extensions/
    contracts/
      ledger/
        v1/
          __init__.py
          schemas/
            event.request.json
            event.response.json
```

## 2) `schemas/event.request.json`

Small, strict core; free-form bags for details/refs. Provider (Ledger slice) will fill ids/hashes.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "event.request.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["domain", "operation", "request_id", "actor_ulid"],
  "properties": {
    "domain": { "type": "string", "minLength": 1 },
    "operation": { "type": "string", "minLength": 1 },
    "happened_at": { "type": "string", "format": "date-time" },
    "request_id": { "type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$" },
    "actor_ulid": { "type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$" },
    "target_ulid": { "type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$" },
    "changed": { "type": "object", "additionalProperties": true },
    "refs": { "type": "object", "additionalProperties": true },
    "correlation_id": { "type": "string", "minLength": 1 }
  }
}
```

Notes

- `happened_at` optional: if omitted, provider sets `utc_now()`.

- `changed`/`refs` are free-form objects that serialize to JSON in the table.

- `target_ulid` optional for system-wide events.

## 3) `schemas/event.response.json`

What the provider returns after append.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "event.response.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["event_ulid", "happened_at", "event_hash"],
  "properties": {
    "event_ulid": { "type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$" },
    "happened_at": { "type": "string", "format": "date-time" },
    "prev_event_ulid": { "type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$" },
    "prev_hash": { "type": "string", "minLength": 8 },
    "event_hash": { "type": "string", "minLength": 8 }
  }
}
```

## 4) Facade: `extensions/contracts/ledger/v1/__init__.py`

Validates both directions; calls the Ledger slice service.

```python
# app/extensions/contracts/ledger/v1/__init__.py
from typing import Dict, Any

from app.extensions.contracts.validate import load_schema, validate_payload
from app.extensions.contracts.errors import ContractDataNotFound
from app.slices.ledger import services as ledger  # provider slice

def emit_event(*, payload: Dict[str, Any]) -> Dict[str, Any]:
    req = load_schema(__file__, "schemas/event.request.json")
    validate_payload(payload, req)

    out = ledger.append_event(payload)  # provider does ulid/hash/prev-link
    res = load_schema(__file__, "schemas/event.response.json")
    validate_payload(out, res)
    return out

def get_event(*, event_ulid: str) -> Dict[str, Any]:
    data = ledger.get_event(event_ulid)  # provider returns dict or None
    if not data:
        raise ContractDataNotFound(f"ledger event '{event_ulid}' not found")
    # Optional: you can validate against a superset schema if you expose a read DTO
    return data
```

## 5) Provider expectations (Ledger slice)

In `app/slices/ledger/services.py` implement:

```python
def append_event(payload: dict) -> dict:
    """
    - Coerce defaults: happened_at = utc_now() if missing
    - Generate event_ulid
    - Read tail -> prev_event_ulid, prev_hash
    - Compute event_hash = sha256(compacted_event_json + prev_hash)[:…]
    - INSERT row (immutable columns)
    - Return {"event_ulid", "happened_at", "prev_event_ulid", "prev_hash", "event_hash"}
    """
    ...

def get_event(event_ulid: str) -> dict | None:
    """Return a dict view of a single event, or None."""
    ...
```

Table sketch (already aligned with your earlier list):

- `event_ulid` (PK, ULID text)

- `domain` (text)

- `operation` (text)

- `happened_at` (UTC Zulu text)

- `request_id` (ULID text)

- `actor_ulid` (ULID text)

- `target_ulid` (ULID text, nullable)

- `changed_json` (text)

- `refs_json` (text)

- `correlation_id` (text, nullable)

- `prev_event_ulid` (ULID text, nullable)

- `prev_hash` (text)

- `event_hash` (text, unique)

## 6) Example usage from another slice (e.g., Governance)

```python
from app.extensions.contracts.ledger.v1 import emit_event
from app.extensions import utc_now
from app.extensions import new_ulid  # or however you expose it

def _log_policy_update(*, key: str, before: dict, after: dict, actor_ulid: str, request_id: str):
    emit_event(payload={
        "domain": "governance",
        "operation": "policy.update",
        "happened_at": utc_now().isoformat().replace("+00:00", "Z"),
        "request_id": request_id,
        "actor_ulid": actor_ulid,
        "target_ulid": None,
        "changed": {"key": key, "before": before, "after": after},
        "refs": {"policy_key": key}
    })
```

That’s it—tiny, strict, versioned, and DRY:

- Callers only know the facade and the two schemas.

- The provider owns how ULIDs/hashes/prev-linking are done.

- The contract guarantees every slice emits consistent, verifiable events.

# JSON error checking

I’d keep them lean, but give them room to carry safe context (so callers/logs
get signal without leaking internals) and add two “sometimes handy” variants.
Here’s a battle-tested pattern:

```python
# app/extensions/contracts/errors.py

from __future__ import annotations
from typing import Any, Optional, Sequence

class ContractError(RuntimeError):
    """
    Base class for contract-layer errors.
    Carries safe (non-PII) context you’re OK exposing to callers/logs.
    """
    code: str = "contract_error"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.details = details or {}
        self.__cause__ = cause  # preserves traceback chaining

class ContractValidationError(ContractError):
    """Payload failed contract schema validation."""
    code = "validation_error"

    @classmethod
    def from_jsonschema(cls, exc: Exception) -> "ContractValidationError":
        # Works with jsonschema.ValidationError
        # Safely extract: message + JSON pointer to the failing location.
        path: Sequence[Any] = getattr(exc, "absolute_path", ()) or getattr(exc, "path", ())
        pointer = "/" + "/".join(map(str, path)) if path else ""
        details = {
            "pointer": pointer,                      # e.g. "/changed/before"
            "validator": getattr(exc, "validator", None),
            "validator_value": getattr(exc, "validator_value", None),
            "message": str(exc),
        }
        return cls("Invalid payload", details=details, cause=exc)

class ContractDataNotFound(ContractError):
    """The requested data was not found in the provider slice."""
    code = "not_found"

class ContractConflict(ContractError):
    """
    Optional: provider reports ‘already exists’, optimistic lock failure,
    hash/prev-link mismatch, etc.
    """
    code = "conflict"

class ContractUnavailable(ContractError):
    """
    Optional: provider temporarily unavailable (DB down, dependency outage).
    Callers may choose to retry.
    """
    code = "unavailable"
```

### Tiny helpers you’ll use in facades

```python
# app/extensions/contracts/validate.py

from importlib.resources import files
import json
from jsonschema import Draft202012Validator
from .errors import ContractValidationError

def load_schema(module_file: str, rel_path: str) -> dict:
    # module_file is __file__ of the contract package; rel_path like "schemas/event.request.json"
    pkg = module_file.rsplit("/", 1)[0]  # package directory
    # Simple loader; if you prefer importlib.resources for packages, use that instead.
    with open(f"{pkg}/{rel_path}", "r", encoding="utf-8") as f:
        return json.load(f)

def validate_payload(payload: dict, schema: dict) -> None:
    try:
        Draft202012Validator(schema).validate(payload)
    except Exception as e:
        raise ContractValidationError.from_jsonschema(e)
```

### How you use them (pattern)

```python
# app/extensions/contracts/ledger/v1/__init__.py

from typing import Dict, Any
from app.extensions.contracts.validate import load_schema, validate_payload
from app.extensions.contracts.errors import (
    ContractDataNotFound,
    ContractConflict,
    ContractUnavailable,
)
from app.slices.ledger import services as ledger

def emit_event(*, payload: Dict[str, Any]) -> Dict[str, Any]:
    req = load_schema(__file__, "schemas/event.request.json")
    validate_payload(payload, req)

    try:
        out = ledger.append_event(payload)  # provider-specific
    except ledger.EventHashConflict as e:
        # Map provider error to contract error (don’t leak provider classes upward)
        raise ContractConflict("Ledger hash conflict", details={"hint": "re-read tail"}, cause=e)
    except ledger.ProviderTemporarilyDown as e:
        raise ContractUnavailable("Ledger unavailable", cause=e)

    res = load_schema(__file__, "schemas/event.response.json")
    validate_payload(out, res)
    return out

def get_event(*, event_ulid: str) -> Dict[str, Any]:
    data = ledger.get_event(event_ulid)
    if not data:
        raise ContractDataNotFound(f"ledger event '{event_ulid}' not found")
    return data
```

### Why this shape works

* **Single base type** with `code`, `details`, `cause` lets you log/serialize
  consistently (e.g., as JSON to your audit logger) without exposing internals.
* **Validation** shows *where* in the payload the issue lives (`pointer`)
  and *what* rule failed.
* **Mapping** keeps provider exceptions behind the facade—callers only handle
  contract errors.
* **Optional conflict/unavailable** cover the most common non-200 paths you’ll
  want to branch on later (retry vs. fix input).

If you want even more structure, you can add a tiny serializer:

```python
def to_dict(err: ContractError) -> dict:
    return {"type": err.__class__.__name__, "code": err.code, "message": str(err), "details": err.details}
```

…but the core above is all you need to start cleanly.
