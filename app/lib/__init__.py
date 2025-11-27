# app/lib/__init__.py

"""
VCDB core library package ("lib-core").

This package contains small, stable building blocks that all slices
(Auth, Entity, Ledger, Resources, Sponsors, etc.) rely on. Each module
does one thing, and public APIs are treated as canon: change them only
with a clear migration plan.

Key modules (not exhaustive):

- ids: ULID helpers and ID primitives
    new_ulid(), is_ulid(), ulid_min_for()/ulid_max_for()

- chrono: UTC/ISO-8601 time helpers used for IDs, logs, and DB fields

- errors: base AppError hierarchy and ContractError for Extensions

- models: SQLAlchemy mixins (ULIDPK, ULIDFK, IsoTimestamps)

- jsonutil: deterministic JSON (stable_dumps) for hashing & ledger

- hashing: thin SHA-256 wrappers, including sha256_json()

- logging: structured JSON logging configuration for the app

- pagination: Page[T] + helpers for list/SQLAlchemy pagination

- request_ctx: request_id and actor_ulid contextvars for logs/ledger

- schema: JSON Schema validation helpers for governance/config

- utils: small validators/normalizers (email, phone, EIN)

- appctx: cfg() accessor for current_app.config inside app context

- db_hooks: SQLite engine hooks
    (e.g., PRAGMA foreign_keys=ON) :contentReference[oaicite:3]{index=3}

- db_middleware: SQLite/SQLAlchemy request guardrails
    GET/HEAD/OPTIONS, (SQLite: PRAGMA query_only=ON)
    Mutating verbs (POST/PUT/PATCH/DELETE) are writable
    On success: mutating verbs commit; safe verbs rollback
    On errors: always rollback
    Always remove the session

Import concrete modules directly; this package does not re-export
symbols. This keeps dependencies explicit and avoids circular imports.

Examples:

    from app.lib.ids import new_ulid
    from app.lib.chrono import now_iso8601_ms
    from app.lib.schema import validate_json

If you need a new cross-slice primitive, add it as a focused function or
mixin in the appropriate module here so lib-core remains the single
source of truth.
"""

__all__: list[str] = []  # explicit: nothing is exported here
