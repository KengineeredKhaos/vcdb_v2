# What to include

- **Schema snapshot**
  
  - Tables, FKs, uniques, enums; note canonical sources (e.g., Governance.Policy vs Entity.Role).
  
  - Any denormalized views/materialized tables.

- **Governance → Policy**
  
  - Keys and value shapes (JSON schemas).
  
  - Validation rules + who can write.
  
  - Event names/payloads for policy changes.

- **Roles lifecycle**
  
  - Authoritative list source (policy key).
  
  - Where roles are persisted per entity.
  
  - Allowed transitions (add/remove) and invariants.

- **Slice responsibilities**
  
  - For each slice: owned tables, write ops, read ops exposed.
  
  - **Extensions interface** each slice exposes (functions, params, return types).

- **Admin adjustments**
  
  - Dry-run/commit flow: inputs, plan structure, apply result, ledger payload.
  
  - Error cases (invalid role, noop, conflict).

- **Auth gates**
  
  - Which routes require which roles; test bypass strategy for CI.

- **Ledger**
  
  - Event taxonomy (e.g., `policy.set`, `role.adjust`), minimal payloads, idempotency rules.

- **Cross-slice calls**
  
  - Who calls whom (only via Extensions), and directionality you want guaranteed.

- **Migrations**
  
  - Any backfill steps (e.g., normalize legacy roles), safety switches, rollout order.

- **Test matrix**
  
  - Unit: services + extensions plan/apply.
  
  - Integration: minimal route smoke (no auth noise), ledger assertion.
  
  - Fixtures: DB setup/teardown, decorator monkeypatching.

When you post the schema + scenarios, I’ll map them to:

1. a small, explicit `extensions` surface (plan/apply + policy reads),

2. DRY service functions inside the owning slices,

3. exact ledger contracts,

4. a slim test suite that won’t fight auth.

I’m ready when you are.
