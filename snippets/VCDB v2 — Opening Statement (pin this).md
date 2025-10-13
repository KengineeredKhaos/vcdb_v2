perfect—let’s spin up the fresh thread cleanly. here’s a tight opener you can paste in to kick things off:

---

# VCDB v2 — Opening Statement (pin this)

## Ethos (pinned)

- Skinny routes, fat services.

- Slices own their data; no cross-slice DB access.

- Extensions is the only bridge (contracts, versioned: v1, v2 side-by-side).

- DTOs + JSON Schema at the boundary.

- ULID everywhere (one entity_ulid from creation to archive).

- Time = UTC (ISO-8601 Z).

- Ledger is the audit spine (append-only, content-hashed, no PII).

- RBAC ≠ domain roles (RBAC in `auth`; domain roles in `entity/governance`).

- Nothing is deleted—only archived per Governance retention.

## What we’re building (v2 baseline)

- **Governance** publishes policies (JSON Schema + values) via contracts.

- **Auth** owns accounts & RBAC.

- **Entity** owns entity lifecycle & domain roles.

- **Admin** does dry-run/commit role adjustments via contracts.

- **Ledger** records all significant events (global chain + optional `chain_key`).

- **Finance (planned)**: CoA, funds/budgets, journals, projections.

## Contract pattern

- `extensions/contracts/<slice>/vN.py` exposes read/write functions that:
  
  - validate with JSON Schema,
  
  - call the slice’s services,
  
  - raise contract-scoped errors,
  
  - emit ledger events where appropriate.

## Initial focus

1. Boot path sane (`create_app()` minimal; config/blueprints/extensions only).

2. Governance policies persisted + exposed (start with roles).

3. Entity v2: ULID PKs, clean role assignment, ledger emits.

4. Admin: role backfill (dry-run/commit), contract-validated, ledgered.

5. Ledger v2 schema: `event_ulid`, `domain`, `operation`, `actor_ulid`, `target_id`, `changed_fields_json`, `refs_json`, `prev_event_id/hash`, `event_hash`, optional `chain_key`.

## Ground rules for PRs

- No new cross-slice imports—go through Extensions.

- Add schema + DTO first, then service, then route/template.

- New inter-slice calls include idempotency keys and ledger events.

- UTC in, UTC out (UI localizes).
