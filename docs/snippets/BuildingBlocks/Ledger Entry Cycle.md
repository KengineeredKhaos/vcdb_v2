# Ledger Entry Cycle

Here’s a tiny, reusable “ledger v1” contract you can drop in. It keeps the core strict and everything else flexible, and it mirrors the ULID + ISO-8601/Zulu conventions we pinned.

# 1) File layout

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

# 2) `schemas/event.request.json`

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

# 3) `schemas/event.response.json`

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

# 4) Facade: `extensions/contracts/ledger/v1/__init__.py`

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

# 5) Provider expectations (Ledger slice)

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

# 6) Example usage from another slice (e.g., Governance)

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
