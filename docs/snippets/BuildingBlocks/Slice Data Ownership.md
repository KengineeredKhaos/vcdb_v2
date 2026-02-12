# VCDB Slice Data Ownership

---

Ethos (the non-negotiables)

- **Skinny routes, fat services.** Routes are glue; business logic lives in services.

- **Slices own their data.** A slice is the *only* place allowed to read/write its tables and compose its SQL.

- **Extensions is the interface.** Slices never import each other; they interact only through **versioned contracts** exposed by `extensions/…`.

- **Contracts, not reach-ins.** Each contract defines: allowed requests, DTO shapes, error model. No cross-slice joins outside the owning slice.

- **Cradle-to-grave ULID.** Every entity is created with a ULID (`str(26)`) that is the primary key everywhere and the anchor in the Ledger.

- **Two role domains, never mixed.**
  
  - **RBAC roles (Auth):** `user`, `auditor`, `admin`.
  
  - **System entity roles (Governance Policy):** `customer`, `resource`, `sponsor`, optional `governor`.

- **Dry-run then commit.** Any mutating admin op supports `dry_run` to preview diffs; `commit` writes and emits a single Ledger event.

- **Everything is auditable.** Ledger events capture `entity_ulid`, `before` → `after`, actor, reason, timestamp.

- **Absolutely no personal identifying information (PII) in ledger or logs.** ULID only.

---

## System Level Factors

- Jinja StrictUndefined (fail early and hard)

- Slices own their data and mechanisms, 

- Slices expose data through contracts: `extensions/contracts/<slice>/v1.py`

- Contract format example
  
  - **Admin contract (v1) – role repair**
    
    Requires **dry-run** first, then **commit** to write changes.
    
    - Request:
      
      `{   "entity_ulid": "<ULID>",   "add": ["sponsor"],   "remove": ["resource"],   "dry_run": true }`
    
    - Response `data`:
      
      `{   "entity_ulid": "<ULID>",   "current_roles": ["customer","resource"],   "result_roles": ["customer","sponsor"],   "diff": { "added": ["sponsor"], "removed": ["resource"] },   "ledger_preview": { "type": "role.repaired", "before": {...}, "after": {...} },   "dry_run": true }`
  
  - **Governance contract (v1) – list allowed entity roles**
    
    - Request: none
    
    - Response `data`:
      
      `{ "roles": ["customer","resource","sponsor","governor"] }`

- `app/logs/`
  
  - `app.log` (system log)
  
  - `audit.log`  ( contains only system "login/logout" data )
    
    - user `entity_ulid`
    
    - authentication attempt fail (timestamp)
    
    - login success (timestamp)
    
    - logout (timestamp)
  
  - `export.log` (contains cron job and manual ledger exports)
    
    - timestamp
    
    - user `entity_ulid` (if available)
    
    - worker task name (if available)
    
    - ledger segment from 'hash'
    
    - ledger segment to 'hash'
  
  - `jobs.log` (standard worker log)

---

## Library (app/lib)

This is the home of system-wide functions/definitions

- init.py (library registration on startup)

- **time.py** alias all SQLite-compatible timestamp functions, local-to-utc and utc-to-local time stamp conversions to unified shorthand conventions

- 

- geo.py (U.S. State JSON library)

- security.py (RBAC wrapper)

- util.py (placeholder for helper functions PRN)
  
  - JSON build helper

### ids.py

```python
# app/lib/ids.py
from ulid import ULID
def new_ulid() -> str: return str(ULID())
```

### time.py

```python
# app/lib/time.py
from datetime import datetime, timezone
from typing import Optional

# Always produce ISO-8601 UTC with 'Z' and 3 decimal milliseconds
def now_utc_iso() -> str:
    dt = datetime.now(timezone.utc)
    # Truncate to milliseconds
    ms = int(dt.microsecond / 1000)
    return dt.replace(microsecond=ms * 1000).isoformat().replace("+00:00", "Z")

def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        # Treat naive as UTC only if it’s explicitly our policy; safer is to reject.
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.replace(microsecond=ms * 1000).isoformat().replace("+00:00", "Z")

def parse_iso8601_to_utc(s: str) -> datetime:
    # Accept 'Z' and offsets; return aware UTC datetime
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Decide: reject naive or assume UTC. Rejecting avoids silent bugs:
        raise ValueError("Naive datetime not allowed; include timezone or 'Z'.")
    return dt.astimezone(timezone.utc)
```

```json
# app/lib/geo.py
# Strict state two letter codes plus DC & PR
# in json format


_STATE_CODES = {
    "AL": {"isoCode": "AL", "name": "Alabama", "abbr": "Ala."},
    "AK": {"isoCode": "AK", "name": "Alaska", "abbr": "Alaska"},
    "AZ": {"isoCode": "AZ", "name": "Arizona", "abbr": "Ariz."},
    "AR": {"isoCode": "AR", "name": "Arkansas", "abbr": "Ark."},
    "CA": {"isoCode": "CA", "name": "California", "abbr": "Calif."},
    "CO": {"isoCode": "CO", "name": "Colorado", "abbr": "Colo."},
    "CT": {"isoCode": "CT", "name": "Connecticut", "abbr": "Conn."},
    "DC": {"isoCode": "DC", "name": "District of Columbia", "abbr": "D.C."},
    "DE": {"isoCode": "DE", "name": "Delaware", "abbr": "Del."},
    "FL": {"isoCode": "FL", "name": "Florida", "abbr": "Fla."},
    "GA": {"isoCode": "GA", "name": "Georgia", "abbr": "Ga."},
    "HI": {"isoCode": "HI", "name": "Hawaii", "abbr": "Hawaii"},
    "ID": {"isoCode": "ID", "name": "Idaho", "abbr": "Idaho"},
    "IL": {"isoCode": "IL", "name": "Illinois", "abbr": "Ill."},
    "IN": {"isoCode": "IN", "name": "Indiana", "abbr": "Ind."},
    "IA": {"isoCode": "IA", "name": "Iowa", "abbr": "Iowa"},
    "KS": {"isoCode": "KS", "name": "Kansas", "abbr": "Kans."},
    "KY": {"isoCode": "KY", "name": "Kentucky", "abbr": "Ky."},
    "LA": {"isoCode": "LA", "name": "Louisiana", "abbr": "La."},
    "ME": {"isoCode": "ME", "name": "Maine", "abbr": "Maine"},
    "MD": {"isoCode": "MD", "name": "Maryland", "abbr": "Md."},
    "MA": {"isoCode": "MA", "name": "Massachusetts", "abbr": "Mass."},
    "MI": {"isoCode": "MI", "name": "Michigan", "abbr": "Mich."},
    "MN": {"isoCode": "MN", "name": "Minnesota", "abbr": "Minn."},
    "MS": {"isoCode": "MS", "name": "Mississippi", "abbr": "Miss."},
    "MO": {"isoCode": "MO", "name": "Missouri", "abbr": "Mo."},
    "MT": {"isoCode": "MT", "name": "Montana", "abbr": "Mont."},
    "NE": {"isoCode": "NE", "name": "Nebraska", "abbr": "Nebr."},
    "NV": {"isoCode": "NV", "name": "Nevada", "abbr": "Nev."},
    "NH": {"isoCode": "NH", "name": "New Hampshire", "abbr": "N.H."},
    "NJ": {"isoCode": "NJ", "name": "New Jersey", "abbr": "N.J."},
    "NM": {"isoCode": "NM", "name": "New Mexico", "abbr": "N.M."},
    "NY": {"isoCode": "NY", "name": "New York", "abbr": "N.Y."},
    "NC": {"isoCode": "NC", "name": "North Carolina", "abbr": "N.C."},
    "ND": {"isoCode": "ND", "name": "North Dakota", "abbr": "N.D."},
    "OH": {"isoCode": "OH", "name": "Ohio", "abbr": "Ohio"},
    "OK": {"isoCode": "OK", "name": "Oklahoma", "abbr": "Okla."},
    "OR": {"isoCode": "OR", "name": "Oregon", "abbr": "Ore."},
    "PA": {"isoCode": "PA", "name": "Pennsylvania", "abbr": "Pa."},
    "PR": {"isoCode": "PR", "name": "Puerto Rico", "abbr": "P.R."},
    "RI": {"isoCode": "RI", "name": "Rhode Island", "abbr": "R.I."},
    "SC": {"isoCode": "SC", "name": "South Carolina", "abbr": "S.C."},
    "SD": {"isoCode": "SD", "name": "South Dakota", "abbr": "S.D."},
    "TN": {"isoCode": "TN", "name": "Tennessee", "abbr": "Tenn."},
    "TX": {"isoCode": "TX", "name": "Texas", "abbr": "Tex."},
    "UT": {"isoCode": "UT", "name": "Utah", "abbr": "Utah"},
    "VT": {"isoCode": "VT", "name": "Vermont", "abbr": "Vt."},
    "VA": {"isoCode": "VA", "name": "Virginia", "abbr": "Va."},
    "WA": {"isoCode": "WA", "name": "Washington", "abbr": "Wash."},
    "WV": {"isoCode": "WV", "name": "West Virginia", "abbr": "W.Va."},
    "WI": {"isoCode": "WI", "name": "Wisconsin", "abbr": "Wis."},
    "WY": {"isoCode": "WY", "name": "Wyoming", "abbr": "Wyo."},
}
```

```python
# app/lib/security.py — simple role gate (placeholder)
from functools import wraps
import logging


audit_logger = logging.getLogger("vcdb.audit")


def roles_required(*role_names):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
        # TODO: integrate Flask-Login & real roles
        audit_logger.info({
            "event": "rbac.check",
            "roles_required": list(role_names),
            "note": "DEV scaffold — allow all",
        })
        return fn(*args, **kwargs)
    return wrapper
return decorator
```

## Extensions Contract Taxonomy

### Envelope (request/error/response)

```python
# extensions/contracts/types.py
from typing import TypedDict, NotRequired

class ContractRequest(TypedDict):
    contract: str                 # e.g., "governance.roles.v1"
    request_id: str               # ULID
    ts: str                       # ISO8601 UTC "…Z"
    actor_ulid: NotRequired[str]  # ULID of caller (if any)
    dry_run: NotRequired[bool]
    data: dict                    # contract-specific payload

class ContractError(TypedDict, total=False):
    code: str                     # "INVALID_ROLE" | "UNKNOWN_ENTITY" | ...
    message: str
    field: NotRequired[str]
    details: NotRequired[dict]

class ContractResponse(TypedDict, total=False):
    contract: str
    request_id: str
    ts: str
    ok: bool
    data: NotRequired[dict]           # contract-specific DTO
    warnings: NotRequired[list[str]]
    errors: NotRequired[list[ContractError]]
    ledger: NotRequired[dict]         # commit-only hints, e.g. {emitted,event_id}
```

### Governance contract (read-only roles)

```python
# extensions/contracts/governance/v1.py
from typing import TypedDict
from datetime import datetime, timezone
from extensions.contracts.types import ContractRequest, ContractResponse

class RolesDTO(TypedDict):
    roles: list[str]

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def list_allowed_roles(req: ContractRequest) -> ContractResponse:
    # In real code: read from Governance slice storage/service
    roles = ["customer","resource","sponsor","governor"]
    return {
        "contract": "governance.roles.v1",
        "request_id": req["request_id"],
        "ts": _now(),
        "ok": True,
        "data": RolesDTO(roles=roles),  # TypedDict validation at callsite
    }
```

### Admin contract (role repair with dry-run/commit)

```python
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
    diff: dict                    # {added:[...], removed:[...]}
    ledger_preview: dict          # present only in dry_run
    dry_run: bool

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def role_repair(req: ContractRequest) -> ContractResponse:
    data: RoleRepairRequest = req["data"]  # type: ignore
    eid = data["entity_ulid"]
    to_add, to_remove = set(data.get("add", [])), set(data.get("remove", []))

    # 1) Current & allowed roles (replace with real services)
    current = ["customer"]
    allowed = {"customer","resource","sponsor","governor"}

    bad_add = sorted(r for r in to_add if r not in allowed)
    bad_rm  = sorted(r for r in to_remove if r not in allowed)
    if bad_add or bad_rm:
        errs = []
        if bad_add: errs.append({"code":"INVALID_ROLE","message":f"Unknown in add: {bad_add}","field":"add"})
        if bad_rm:  errs.append({"code":"INVALID_ROLE","message":f"Unknown in remove: {bad_rm}","field":"remove"})
        return {"contract":"admin.role_repair.v1","request_id":req["request_id"],"ts":_now(),"ok":False,"errors":errs}

    result = sorted((set(current) | to_add) - to_remove)
    diff = {"added": sorted(set(result)-set(current)), "removed": sorted(set(current)-set(result))}

    ledger_evt = {
        "type": "role.repaired",
        "domain": "governance",
        "operation": "update_roles",
        "happened_at_utc": _now(),
        "actor_id": req.get("actor_ulid"),
        "target_id": eid,
        "changed_fields_json": {"before":{"roles":current}, "after":{"roles":result}, "diff": diff},
        "refs_json": {"contract": "admin.role_repair.v1", "request_id": req["request_id"]},
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
            ledger_preview={},   # omit in commit
            dry_run=False,
        ),
        "ledger": {"emitted": True},       # you can include event_id if available
    }
```

### DTO Shape

```python
# extensions/contracts/governance/v1.py
from typing import TypedDict
from extensions.contracts.types import ContractRequest, ContractResponse
from app.lib import time

class RolesDTO(TypedDict):
    roles: list[str]  # read from Governance policy_roles 

def list_allowed_roles(req: ContractRequest) -> ContractResponse:
    # No input in req["data"]
    roles = ["customer", "resource", "sponsor", "governor"]  # read from Governance policy_roles
    return {
        "contract": "governance.roles.v1",
        "request_id": req["request_id"],
        "ts": timestamp(),
        "ok": True,
        "data": {"roles": roles},
    }
```

### Error codes (base set)

- `UNKNOWN_ENTITY` – ULID not found

- `INVALID_ROLE` – role not in governance policy

- `FORBIDDEN` – actor lacks RBAC permission

- `POLICY_VIOLATION` – operation violates governance constraints

- `CONFLICT` – concurrent update/mismatched version

- `BAD_REQUEST` – malformed input

### Naming & versioning

- Contract name: `"<slice>.<capability>.v<major>"`, e.g. `governance.roles.v1`, `admin.role_repair.v1`.

- Keep **v1** stable; add **v2** alongside it when shapes/behavior change.

### Minimal call pattern (Extensions façade)

```python
# extensions/__init__.py (router sketch)
from ulid import ULID
from app.lib import time
from extensions.contracts.types import ContractRequest
from extensions.contracts.governance.v1 import list_allowed_roles
from extensions.contracts.admin.v1 import role_repair

def _ts():
    return timestamp.now(timezone.utc).isoformat()

def call(contract: str, data: dict, actor_ulid: str | None = None, dry_run: bool | None = None):
    req: ContractRequest = {
        "contract": contract,
        "request_id": str(ULID()),
        "ts": _ts(),
        "data": data,
    }
    if actor_ulid:
        req["actor_ulid"] = actor_ulid
    if dry_run is not None:
        req["dry_run"] = dry_run

    if contract == "governance.roles.v1":
        return list_allowed_roles(req)
    if contract == "admin.role_repair.v1":
        return role_repair(req)
    raise ValueError(f"Unknown contract: {contract}")
```

## ULID Generation Rules and Usage

- `entity.ulid` is **the** primary key (CHAR(26) or VARCHAR(26), indexed).

- All slice tables that reference an entity must use `entity_ulid` (same type/length) and foreign keys where appropriate.

- `auth_user.user_ulid` references `entity.ulid` (when a person has an account).  

- **Generation**: ULID is generated in **Entity service** at creation time (not by DB, not by caller).

```python
# app/lib/ids.py
from ulid import ULID


def new_ulid() -> str:
    return str(ULID())  # 26-char, k-sortable
```

## Entity Slice Owns (rough format)

- entity
  
  - entity_ulid (generated ULID)
  
  - created at (timestamp)
  
  - updated at (timestamp)
  
  - kind (select: person | org)
    
    - person
      
      - entity_ulid
      
      - first name
      
      - last name
      
      - preferred name
    
    - org
      
      - entity_ulid
      
      - ein
      
      - legal name
      
      - dba name

- contact
  
  - entity_ulid
    
    - created at
    
    - updated at
  
  - kind
    
    - email
      
      - value (validated)
    
    - phone
      
      - value (validated)
    
    - is_primary
      
      - (bool)

- address
  
  - entity_ulid
  
  - purpose (select: mailing | physical)
  
  - address1
  
  - address2
  
  - city
  
  - state
    
    - validate (two-letter identifier against app/lib/geo.py)
  
  - postal
  
  - tz
  
  - is_primary
  
  - created at
  
  - updated at

- entity role
  
  - entity_ulid
  
  - role code
    
    - retrieved from governance slice through
       extensions.contracts.get_role_codes
    
    - select: governance role code (customer | resource | sponsor)
  
  - granted at

- entity role (roles_required(admin))
  
  - entity_ulid
  
  - role code (governor)
  
  - granted at

---

## Admin Slice Owns

- cron_status
  
  - job_name
  
  - last_success_utc
  
  - last_error_utc
  
  - last_error

- RBAC roles
  
  - `user` (read + routine writes within policy)
  
  - `auditor` (read-all, export, inspect ledger)
  
  - `admin` (manage users, RBAC, config, feature flags—not business data decisions)

---

## Auth Slice Owns

- users
  - entity_ulid
  - username
  - email
  - is_active
  - created_at
  - updated_at
  - password_hash
  - must_change_password
  - pw_change_at
- roles
  - { sys_roles: ["auditor","user","admin"] } 
    - where auditor=read-only, user=CRU, admin=CRUD
- user_roles
  - entity_ulid
  - sys_role

---

## Ledger Slice Owns

- ledger entry minimum spec
  - ledger.id (ULID)
  - (expansion field 1)
  - type
  - domain (admin | entity | customer | resource | sponsor | governance |...)
  - operation
  - happened_at (timestamp) 
  - request_id (ULID)
  - actor_id (entity_ulid)
  - target_id (entity_ulid)
  - (expansion field 2)
  - changed_fields_json
  - refs_json
  - correlation_id
  - prev_event_id
  - prev_hash
  - event_hash

### Ledger Table

```python
-- TABLE: ledger_events
CREATE TABLE ledger_events (
  id               TEXT PRIMARY KEY,                -- ULID (event id)
  type             TEXT NOT NULL,                   -- e.g., "role.repaired"
  domain           TEXT NOT NULL,                   -- e.g., "governance" | "admin" | "entity" | ...
  operation        TEXT NOT NULL,                   -- action verb: "update_roles", "create", "delete", ...
  happened_at_utc  TEXT NOT NULL,                   -- ISO8601 UTC (e.g., 2025-01-01T12:34:56.789Z)
  request_id       TEXT,                            -- ULID of the originating request/envelope
  actor_id         TEXT,                            -- ULID of the actor (entity ulid), nullable for system
  target_id        TEXT,                            -- ULID of the main subject entity of the event
  -- Expansion fields (free-form JSON for future-proofing)
  changed_fields_json TEXT NOT NULL DEFAULT '{}',   -- JSON {before:{}, after:{}}, or {"diff":{...}}
  refs_json           TEXT NOT NULL DEFAULT '{}',   -- JSON for auxiliary references (e.g., {"policy_key": "..."}
  -- Correlation & chain
  correlation_id   TEXT,                            -- tie multiple events in one high-level operation
  prev_event_id    TEXT,                            -- ULID of the immediately-preceding event (optional)
  prev_hash        TEXT,                            -- SHA-256 hex of prev event canonical JSON (optional)
  event_hash       TEXT NOT NULL                    -- SHA-256 hex of *this* event’s canonical JSON
);

-- Useful indexes
CREATE INDEX idx_ledger_happened_at ON ledger_events (happened_at_utc);
CREATE INDEX idx_ledger_domain_op   ON ledger_events (domain, operation);
CREATE INDEX idx_ledger_actor       ON ledger_events (actor_id);
CREATE INDEX idx_ledger_target      ON ledger_events (target_id);
CREATE INDEX idx_ledger_request     ON ledger_events (request_id);
CREATE INDEX idx_ledger_corr        ON ledger_events (correlation_id);
```

### Notes / invariants

- **Immutability:** rows are append-only; no updates/deletes except in catastrophic admin repair (which itself should emit a repair event).

- **event_hash** is computed over a **canonical JSON** representation of the event.

- **prev_event_id/prev_hash** give you a *hash chain*. You can chain:
  
  - per-**domain**, or
  
  - per-**target_id** (entity chain),
  
  - or a single global chain (if you pass the most recent global event).  
    Pick one rule and document it; most teams use **per-target_id** for fast verification of an entity’s history.

- **correlation_id** groups multiple events created during one higher-level action (ULID; e.g., “bulk role repair” writes 1 event per entity but shares one correlation_id).

### Changed_fields_json:

```json
{
  "before": {"roles": ["customer"]},
  "after":  {"roles": ["customer","sponsor"]},
  "diff":   {"added": ["sponsor"], "removed": []}
}
```

### Canonical event JSON (for hashing)

To make `event_hash` stable and verifiable:

- Build a dict with **exact** keys and order them by **sorted keys**.

- **Exclude** `event_hash` itself from the material used to compute the hash (hash can’t contain itself).

- Use `json.dumps(obj, separators=(',', ':'), sort_keys=True, ensure_ascii=False)` and hash the **UTF-8 bytes** via SHA-256, hex-encode.

**Canonical payload used for hashing (example):**

```json
{
  "id": "01J8K...ULID",
  "type": "role.repaired",
  "domain": "governance",
  "operation": "update_roles",
  "happened_at_utc": "2025-01-01T12:34:56.789Z",
  "request_id": "01J8K...ULID",
  "actor_id": "01H...ULID",
  "target_id": "01H...ULID",
  "changed_fields_json": {"before": {"roles": ["customer"]}, "after": {"roles": ["customer","sponsor"]}, "diff": {"added":["sponsor"],"removed":[]}},
  "refs_json": {"request_id": "01J8K...ULID"},
  "correlation_id": "01J8K...ULID",
  "prev_event_id": "01J8J...ULID",
  "prev_hash": "ab12...ef"
}
```

`event_hash = sha256(canonical_json_without_event_hash).hexdigest()`

### Ledger service: set the two timestamps

```python

```

### Ledger Contract

**DTOs (request/response)**

```python
# extensions/contracts/ledger/v1.py
from typing import TypedDict, NotRequired

class LedgerEmitRequest(TypedDict, total=False):
    id: NotRequired[str]                 # optional; generally generated by service
    type: str
    domain: str                          # "admin" | "entity" | "customer" | "resource" | "sponsor" | "governance" | ...
    operation: str                       # "create" | "update_roles" | ...
    happened_at_utc: NotRequired[str]    # default now() UTC if not provided
    request_id: str                      # ULID of the higher-level call
    actor_id: NotRequired[str]           # ULID or None
    target_id: NotRequired[str]          # ULID or None
    changed_fields_json: NotRequired[dict]
    refs_json: NotRequired[dict]
    correlation_id: NotRequired[str]
    # Chain policy (usually per target_id). You supply the "previous" pointers.
    prev_event_id: NotRequired[str]
    prev_hash: NotRequired[str]

class LedgerEmitDTO(TypedDict):
    id: str
    event_hash: str
    preview: bool
```

**Implementation sketch**

```python
# extensions/contracts/ledger/v1.py
from datetime import datetime, timezone
from typing import cast
import json, hashlib
from ulid import ULID
from extensions.contracts.types import ContractRequest, ContractResponse
# from app.slices.ledger.services import insert_event, fetch_last_for_target  # your slice-owned functions

ALLOWED_DOMAINS = {"admin","entity","customer","resource","sponsor","governance"}  # extend as needed

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _canonical_for_hash(event: dict) -> bytes:
    # Do not include event_hash itself
    e = {k: v for k, v in event.items() if k != "event_hash"}
    return json.dumps(e, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

def _hash_event(event: dict) -> str:
    return hashlib.sha256(_canonical_for_hash(event)).hexdigest()

def emit(req: ContractRequest) -> ContractResponse:
    from typing import Dict, Any
    data = cast(Dict[str, Any], req["data"])

    # Validate mandatory
    missing = [k for k in ("type","domain","operation","request_id") if k not in data]
    if missing:
        return {
            "contract": "ledger.emit.v1",
            "request_id": req["request_id"],
            "ts": _now_iso(),
            "ok": False,
            "errors": [{"code": "BAD_REQUEST", "message": f"Missing fields: {missing}"}],
        }

    if data["domain"] not in ALLOWED_DOMAINS:
        return {
            "contract": "ledger.emit.v1",
            "request_id": req["request_id"],
            "ts": _now_iso(),
            "ok": False,
            "errors": [{"code": "BAD_REQUEST", "message": f"Unknown domain '{data['domain']}'", "field": "domain"}],
        }

    event = {
        "id": data.get("id") or str(ULID()),
        "type": data["type"],
        "domain": data["domain"],
        "operation": data["operation"],
        "happened_at_utc": data.get("happened_at_utc") or _now_iso(),
        "request_id": data["request_id"],
        "actor_id": data.get("actor_id"),
        "target_id": data.get("target_id"),
        "changed_fields_json": data.get("changed_fields_json") or {},
        "refs_json": data.get("refs_json") or {},
        "correlation_id": data.get("correlation_id"),
        "prev_event_id": data.get("prev_event_id"),
        "prev_hash": data.get("prev_hash"),
    }

    # If you chain per target, you could auto-fill prev_* here by looking up the last event for target_id
    # if event["target_id"] and not event["prev_event_id"]:
    #     prev = fetch_last_for_target(event["target_id"])
    #     if prev:
    #         event["prev_event_id"] = prev.id
    #         event["prev_hash"] = prev.event_hash

    event["event_hash"] = _hash_event(event)

    if req.get("dry_run", False):
        return {
            "contract": "ledger.emit.v1",
            "request_id": req["request_id"],
            "ts": _now_iso(),
            "ok": True,
            "data": {"id": event["id"], "event_hash": event["event_hash"], "preview": True},
        }

    # Commit: persist in Ledger slice (owned data)
    # insert_event(event)  # Your slice service writes it and enforces append-only
    return {
        "contract": "ledger.emit.v1",
        "request_id": req["request_id"],
        "ts": _now_iso(),
        "ok": True,
        "data": {"id": event["id"], "event_hash": event["event_hash"], "preview": False},
    }
```

**How other slices call it (two-liner)**

From Admin’s role-repair commit path, after updating the entity’s roles:

```python
from extensions import call

_ = call(
  "ledger.emit.v1",
  data={
    "type": "role.repaired",
    "domain": "governance",
    "operation": "update_roles",
    "request_id": req["request_id"],
    "actor_id": req.get("actor_ulid"),
    "target_id": entity_ulid,
    "changed_fields_json": {"before": {"roles": curr}, "after": {"roles": new}, "diff": diff},
    "refs_json": {"policy_version": "v1", "contract": "admin.role_repair.v1"},
    "correlation_id": req["request_id"]
  },
)
```

### Ledger contract (emit)

```python
# extensions/contracts/ledger/v1.py
from typing import TypedDict, NotRequired, cast
from datetime import datetime, timezone
import json, hashlib
from ulid import ULID
from extensions.contracts.types import ContractRequest, ContractResponse

ALLOWED_DOMAINS = {"admin","entity","customer","resource","sponsor","governance"}

class LedgerEmitRequest(TypedDict, total=False):
    id: NotRequired[str]
    type: str
    domain: str
    operation: str
    happened_at_utc: NotRequired[str]
    request_id: str
    actor_id: NotRequired[str]
    target_id: NotRequired[str]
    changed_fields_json: NotRequired[dict]
    refs_json: NotRequired[dict]
    correlation_id: NotRequired[str]
    prev_event_id: NotRequired[str]
    prev_hash: NotRequired[str]

class LedgerEmitDTO(TypedDict):
    id: str
    event_hash: str
    preview: bool

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _hash(event: dict) -> str:
    # Exclude event_hash itself to compute the hash
    e = {k: v for k, v in event.items() if k != "event_hash"}
    payload = json.dumps(e, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def emit(req: ContractRequest) -> ContractResponse:
    data = cast(LedgerEmitRequest, req["data"])
    missing = [k for k in ("type","domain","operation","request_id") if k not in data]
    if missing:
        return {"contract":"ledger.emit.v1","request_id":req["request_id"],"ts":_now(),"ok":False,
                "errors":[{"code":"BAD_REQUEST","message":f"Missing fields: {missing}"}]}
    if data["domain"] not in ALLOWED_DOMAINS:
        return {"contract":"ledger.emit.v1","request_id":req["request_id"],"ts":_now(),"ok":False,
                "errors":[{"code":"BAD_REQUEST","field":"domain","message":f"Unknown domain '{data['domain']}'"}]}

    event = {
        "id": data.get("id") or str(ULID()),
        "type": data["type"],
        "domain": data["domain"],
        "operation": data["operation"],
        "happened_at_utc": data.get("happened_at_utc") or _now(),
        "request_id": data["request_id"],
        "actor_id": data.get("actor_id"),
        "target_id": data.get("target_id"),
        "changed_fields_json": data.get("changed_fields_json") or {},
        "refs_json": data.get("refs_json") or {},
        "correlation_id": data.get("correlation_id"),
        "prev_event_id": data.get("prev_event_id"),
        "prev_hash": data.get("prev_hash"),
    }
    event["event_hash"] = _hash(event)

    if req.get("dry_run", False):
        return {"contract":"ledger.emit.v1","request_id":req["request_id"],"ts":_now(),"ok":True,
                "data": LedgerEmitDTO(id=event["id"], event_hash=event["event_hash"], preview=True)}

    # Persist via Ledger slice service here (append-only)
    return {"contract":"ledger.emit.v1","request_id":req["request_id"],"ts":_now(),"ok":True,
            "data": LedgerEmitDTO(id=event["id"], event_hash=event["event_hash"], preview=False)}
# app/lib/ids.py
from ulid import ULID
def new_ulid() -> str: return str(ULID())
```

---

## Customer Slice Owns (unstructured)

- customer profile data 
  
  - Needs Assessment
    
    - **Purpose:** quick triage across domains.
    
    - **Scale:** "1"=immediate, "2"=marginal, "3"=sufficient, default, "N/A".
      
      - store only digit or N/A (str(3))
    
    - **Source:** observed / staff‑assessed.
    
    - **Table Fields**
      
      - **Tier 1 physiological fields:** 
        
        - food (1-3 | N/A)
        
        - hygiene, (1-3 | N/A)
        
        - health (1-3 | N/A)
        
        - housing (1-3 | N/A) 
        
        - clothing (1-3 | N/A)
      
      - **Tier 2 security fields:** 
        
        - income (1-3 | N/A)
        
        - employment (1-3 | N/A)
        
        - transportation (1-3 | N/A)
        
        - education (1-3 | N/A)
      
      - **Tier 3 social fields:** 
        
        - family (1-3 | N/A)
        
        - peer_group (1-3 | N/A) 
        
        - tech (1-3 | N/A)
      
      - assessment (timestamp)
      
      - reevaluation (timestamp)
      
      - interviewer (entity_ulid)
      
      - customer (entity_ulid)

- area/locale demographic (governance: policy_gis)

- branch of service (governance: policy_bos)

- service_era demographic (governance: policy_era)

- inventory draw history
  
  - limit flags on certain inventory items

- referrals to services history

- dates of interactions history

---

## Resource Slice Owns (unstructured)

- service profile
  
  - specialty
  
  - limitations

- hours of operation

- availability/capacity

- primary POC (entity_id)

- Secondary POC (entity_id)

- HIPAA Resrictions

- MOU/SLA onfile
  
  - signing date
  
  - sunset

---

## Sponsor Slice Owns (unstructured)

- donation history

- current tier
  
  - bronze/valued sponsor
  
  - silver/affiliate
  
  - gold/partner

- org type
  
  - private party
  
  - corporation
  
  - foundation
  
  - government entity
  
  - service club/org

- Primary POC

- Secondary POC

- current status
  
  - prospective
  
  - active
  
  - lapsed

- donation type
  
  - monetary
  
  - in-kind
  
  - grant funds
    
    - expenditure tracking
      
      - reporting requirements
      
      - time-frame/duration
      
      - funding sunset
  
  - donation restrictions
    
    - local-only
    
    - veteran-only

- media/press
  
  - logo usage
  
  - press release consent/restrictions

- recognition
  
  - restrictions
  
  - tracking/promise/fulfillment
  
  - history

- risk/fit
  
  - brand alignment rating 1-5
  
  - reputation 1-5

---

## Logistics Slice Owns (unstructured)

- Inventory Item SKU's
  
  - SKU
    
    - see SKU format.md
  
  - nomenclature
  
  - qty on-hand
  
  - qty staged (committed in kits not available for single-item issue)
    
    - Hygiene Kit items
    
    - Kitchen Kit consumables
    
    - durable/consumable goods required for mission support
  
  - min (minimum shelf stock quantity req. to cover restock lead-time)
  
  - max (maximum shelf stock allowed)
  
  - order_point ()
  
  - case_lot (case lot quantity)
  
  - primary resource_id (primary supplier)
  
  - LKQ resource_id (like-kind&quality supplier)
  
  - per-Customer limits (bool toggle)
    
    - annual (boots)
    
    - quarterly (camp gear)
    
    - monthly (toiletries)
    
    - none

- Kit Building
  
  - inventory items are assembled into kits by SKU and Qty.
    
    - Hygiene kits
  
  - Customer kits are built & issued PRN
  
  - Event kits are assembled to support scheduled event
    
    - Elks Welcome Home kit
    
    - Memorial Run checkpoint kit
    
    - pre-planned mission support
  
  - Event kits consist of durable goods and consumables SKU's
    
    - pre-built and staged
    
    - SKU's earmarked as committed (qty staged)

- TODO 
  
  - Physical count cadence
  
  - Reorder - Restock cadence
  
  - Spending authority
  
  - Grant funds expenditure tracking

---

## Asset Slice Owns (unstructured)

- Fixed assets (durable goods, high-value items & major end-items)
  
  - asset_id
  
  - SKU (for durable goods only)
  
  - nomenclature (brief description, unique characteristic)
  
  - serial number
  
  - receipt_holder
  
  - issue_date
  
  - return_date

---

## Governance Slice Owns (unstructured)

Static HTML docs live in:
 `app/static/governance_docs/<doc_name>.html`
Attachments stored in `.pdf` format in respective `app/static/governance_docs/<folder_name>/<file_name>`# extensions/contracts/types.py

from typing import TypedDict, Literal, NotRequired
from datetime import datetime

ContractName = str  # e.g., "governance.roles.v1" or "admin.role_repair.v1"

class ContractRequest(TypedDict):
    contract: ContractName                 # "governance.roles.v1"
    request_id: str                        # ULID string
    ts: str                                # ISO8601 UTC timestamp
    actor_ulid: NotRequired[str]           # ULID of caller (if any)
    dry_run: NotRequired[bool]
    data: dict                             # Contract-specific payload

### Governance Policy:

### Governance "policy_roles"

`{ "roles": ["customer", "resource", "sponsor", "governor"] }`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["roles"],
  "properties": {
    "roles": {
      "type": "array",
      "items": { "type": "string", "minLength": 1},
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```

### Governance "policy_gis"

`{ "locale": ["Lakeport", "Blue Lakes", "Scotts Valley", "Upper Lake", "Nice", "Lucerne", "Oaks", "Clearlake", "Lower Lake", "Middletown", "Hidden valley", "Cobb", "Out of County] }`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["locale"],
  "properties": {
    "locale": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 },
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```

### Governance "policy_branches"

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": false,
    "required": ["bos"],
    "properties": {
      "bos": {
        "type": "array",
        "items": { "type": "string", "enum": "USA","USMC","USN","USAF","USCG","USSF"] },
        "minItems": 1,
        "uniqueItems": true
      }
    }
}
```

### Governance "policy_era"

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
   "type": "object",
   "additionalProperties": false,
   "required": ["era"],
   "properties": {
     "era": {
     "type": "array",
     "items": { "type": "string", "enum": ["korea","vietnam","coldwar","lebanon-grenada-panama","bosnia-herz","persian-gulf","iraq","afghanistan","africa"] },
     "minItems": 1,
     "uniqueItems": true
    }
  }
}
```

- Articles of Incorporation (stored as static html doc)

- Bylaws (stored as static html doc)

- Conflict of Interest Policy (stored as static html doc)

- Board of Directors 
  
  - meeting agenda (stored as attachment doc)
  
  - meeting minutes (stored as attachment doc)
  
  - committee chair reports (stored as attachment doc)
  
  - Board President elections (stored as attachment doc)
  
  - committee chair appointments (stored as attachment doc)
  
  - delegation of authority (stored as attachment doc)
  
  - policy & procedure guidelines (stored as attachment doc)
  
  - MOU/SLA signature authority/delegation (stored as attachment docs)
  
  - Officer duties & responsibilities meeting agenda (stored as static doc)
    
    - Board President
    
    - Vice President (operations)
    
    - Vice President (logistics)
    
    - Secretary
    
    - Treasurer
    
    - Registered Agent
  
  - Pro Tempore assignment and duration
    
    - President pro tem
    
    - Secretary pro tem
    
    - Treasurer pro tem
  
  - Spending Authority
    
    - Special Event Committee Chair
    
    - Petty Cash policy
    
    - Company Check policy
    
    - General Ledger/Accounting policy
  
  - Secretary of State compliance/Form 990 Tax filings
  
  - Public Disclosure requirements/policy/compliance

- Business & Special Events liability insurance (stored as static pdf)

- Software System/Database Management policy (stored as static html doc)

- Grant Funds accountability policy (stored as static html doc)

- Staffing policy (stored as static html doc)
  
  - Hours of Operation policy
  
  - Role/Shift assignments

- Standing Operating Procedures (stored as static html doc)
  
  - Vetting Standards
  
  - Customer Classification/Eligibility for Services
  
  - Walk-in Customer
  
  - Donation policy
    
    - Solicitations
    
    - Accepting in-kind donations
    
    - Accepting monetary donations
  
  - Special Events Planning/Spending Authorities Guidelines
  
  - Field Operations/Security

---

## Calendar Slice Owns (unstructured)

- Special Events scheduling
  
  - event Kanban/Timeline implementation
  
  - kit requirements
  
  - kit build-out scheduling
  
  - staffing requirements/scheduling
  
  - vendor/resource coordination/scheduling
  
  - promotion scheduling

- Grant Funding reporting requirements
  
  - deadline
  
  - periodic reports scheduling

- Business/BofD meetings
  
  - meeting scheduling by type (business/BoD)
  
  - Officer Elections scheduling
  
  - committee chair reports scheduling
  
  - deadline management
  
  - agenda/outline preparation

---

## Communications Slice Owns (unstructured)

### Not sure how all this relates to/integrates with database/system operations just yet.

- e-mail/internal notification systems management
  
  - internal messaging (SysAdmin/Staff)
    
    - trouble desk
    
    - user password reset requests
    
    - cron job success/failure notifications 
  
  - external
    
    - Meeting notifications/invitations
    
    - Event Promotions/E-mail blasts
    
    - e-mail address groupings
    
    - Administrator-Only cron job status notifications

- Event Promotions

- Event swag/spiffs

- Press Releases

- Vendor Save-the-date thru Thank-you's communications plan

- Sponsor Development

- Sponsor Recognition
  
  - certificates/plaques/trophies
  
  - photo-ops
  
  - press releases
  
  - logo'd gear for affiliates
  
  - non-voting/stakeholder BoD position for partners

- Staff Appreciation coordination 
