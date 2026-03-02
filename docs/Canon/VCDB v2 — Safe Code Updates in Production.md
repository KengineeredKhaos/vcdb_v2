# VCDB v2 — Safe Code Updates in Production

## How to ship changes without breaking the app or causing migration crises

This note is a practical guide for updating a running VCDB v2 deployment  
without breaking the app or triggering surprise database migrations.

**Core principle:** A production code deploy is “safe” when it is  
**database-compatible** with the schema and data already in production.

---

## Definitions

- **Code deploy:** Replace application code (and templates/static assets) and  
  restart the service.

- **Migration:** Any intentional change to the database schema (DDL): new tables,  
  columns, constraints, indexes, type changes, etc.

- **Data backfill:** A one-time transformation of existing rows. This may be run  
  by a CLI job or admin workflow. It is not necessarily a schema migration, but  
  it still needs change control.

---

## The Three Buckets

### 1) Do as thou wilst

**Safe drop-in replacements** (normally OK as “replace files + restart”)

**Templates & static assets**

- Jinja templates, macros, CSS/JS/images, copy/labels/layout

- New templates/partials/includes

- New UI routes that only **read existing data**

**Internal refactors (no interface change)**

- Refactor services/repos/mappers

- Improve validations, error messages, logging

- Query optimizations that don’t require new columns/indexes

**Additive functionality**

- New endpoints/routes that don’t require schema changes

- New CLI/dev diagnostics

- New Ledger event *types* (additive only)

**Taxonomy changes that are additive**

- Add new enum values / form options / classification keys

- Add new SKU patterns (if parser supports them)

- Add new states/status values, as long as old stored values remain valid

**Rule:** existing stored values must remain acceptable and meaningful.

---

### 2) Don’t make a habit of it

Usually OK, but has sharp edges (can break old records or workflows)

**Tightening validations**

- Making a previously optional field required

- Rejecting formats that exist in older rows

- Changing defaults so old records fail new checks

**Renaming taxonomy keys that are stored in DB**

- Example: changing role/status strings

- This breaks filters/queries immediately unless you keep compatibility

**Editing cross-slice contract shapes in place**

- Prefer versioning: publish a new contract version instead of mutating v1

**Adding DB CHECK constraints on enums**

- Feels “correct” but forces schema migrations whenever taxonomy grows

- If you want fewer migrations, enforce enums in application logic instead

**Compatibility pattern:** *accept old, write new*

- Read both old and new forms

- Write only the new form going forward

- Keep aliases for old values a long time (possibly forever)

---

### 3) Verboten (treat as planned changes)

These require explicit migration/rollout planning.

**Schema changes**

- Add/rename/drop columns or tables

- Change column types

- Add FKs/constraints that might fail on existing rows

- Index changes that materially affect large tables

**Renaming columns/tables used by running code**

- Classic “deploy boots but crashes on first request”

- Use a multi-release pattern (below)

**Changing primary key / ULID semantics**

- Any change to ULID format, PK type, join keys, or ID generation strategy

**Reinterpreting historical Ledger events**

- Ledger is an audit trail: never change the meaning of old events

- Add new event types instead

---

## The Compatibility Playbook

### A) Two-release rename (safe for production)

Use this when you must rename a column/field/key.

**Release 1**

1. Add new column/field (migration)

2. Code writes both old and new (or writes new and keeps old intact)

3. Code reads old (or reads new with fallback to old)

**Backfill (between releases)**

- Run a data backfill job to populate the new field for existing rows

**Release 2**

1. Code reads new

2. Stop writing old

3. Later: drop old column in a cleanup migration

This avoids “flag day” deploys.

---

### B) Taxonomy evolution without migration crises

**Rule:** Never rename or delete a taxonomy key once it has been stored in the DB.  
Only add new keys. If you want a “rename,” implement it as aliases.

Why: stored strings become part of your data contract.

---

## Where to Store Taxonomy in Production (so updates don’t require migrations)

Choose based on expected rate of change.

### Pattern 1 — Taxonomy in code (simple; requires redeploy)

- Values live in slice-local `taxonomy.py`

- To change taxonomy: deploy new code + restart

**Pros:** simplest  
**Cons:** requires redeploy for every taxonomy tweak

### Pattern 2 — Taxonomy in JSON files on disk (Admin-managed; no redeploy)

- Store editable JSON under a writable `var/` directory

- Validate with JSON Schema + semantic checks

- Gate changes behind Admin UI + approvals + audit

**Pros:** no redeploy; no schema churn  
**Cons:** requires tooling + guardrails

### Pattern 3 — Taxonomy in DB tables (data updates; no schema changes)

- Create tables once

- Adding values is inserting rows (no DDL)

- Admin UI manages values + approvals

**Pros:** queryable; stable; no DDL for new values  
**Cons:** requires admin workflows and careful permissions

**VCDB v2 pragmatic default:** start with Pattern 1; move fast-changing  
taxonomies to Pattern 2 (or 3) once workflows stabilize.

---

## Deployment Guardrails (operational)

- **Pin migrations to explicit releases**; never let schema drift “accidentally”

- **Run smoke checks:** app boots; key routes load; golden path flows work

- **Prefer additive changes** until the system is stable

- **Record releases:** git SHA + migration IDs + any backfill job IDs/hashes

If you keep your production codebase read-only/immutable:

- code lives under `/srv/vcdb/app` (read-only)

- only `/srv/vcdb/var/...` is writable

- anything “editable at runtime” (policy/taxonomy JSON) must live in var paths

---

## Quick Checklist: is this change safe to deploy?

Answer “yes” to all:

- No schema change required

- Existing stored values remain valid

- Contracts used by other slices remain compatible (or versioned)

- New validations won’t break old records (or you used accept-old/write-new)

- Ledger meanings remain unchanged (new event types are fine)

- Rollback won’t leave DB in an incompatible state

If any box is “no,” treat it as a planned migration/rollout with approvals.

---

## Notes for later (closer to production)

- Tighten route guards + PII gating (RBAC + approvals)

- Use “two-person rule” for high-impact admin ops (policy edits, inventory recon)

- Add file hashing + snapshot metadata for any bulk operations (CSV import/export)
