# VCDB v2 — Ethos & Canon Invariants

These are the non-negotiable rules that keep VCDB v2 maintainable, auditable,
and safe. If a change conflicts with any item below, the change is wrong by
definition and must be redesigned.

**Nothing happens in the dark. Nothing is deleted; only archived.**

---

## 0) Vocabulary and Intent

- **Wizard** = creation-only golden path.
  
  - Linear, guarded against resubmits/back-button.
  - Emits `wizard_*` events.
  - Ends at **Review/Confirm + handoff**.

- **Edit Surface** = mutation-only paths.
  
  - Non-linear; can be visited anytime.
  - Emits `entity_*` “facts changed” events.
  - May grow richer over time (diffs/history/etc.).

---

## 1) Architecture & Slice Boundaries

### Skinny routes, fat services

- **Routes orchestrate**: parse/authorize/respond.
- **Services own business logic**: normalize/validate, read/write, flush.

Transaction rules:

- **Routes/CLI own the transaction boundary.**
  
  - Routes/CLI do `commit/rollback` and handle error boundaries.
  - Services may `flush()` but never `commit()` or `rollback()`.

- **One boundary invocation = one transaction.**
  
  - A single UI action / HTTP request / CLI command generates one invocation.
  - That invocation is a single unit of work at the route/CLI boundary.

### Slice ownership is non-negotiable

- **Vertical slices own their tables.**
  
  - A slice may read/write only its own tables.
  - No cross-slice DB reach-arounds.

- **No cross-slice imports.**
  
  - Slices do not import other slices directly or indirectly.

### Extensions is the only bridge

- **All inter-slice calls go through `extensions/contracts`.**
- Contracts are the integration surface; direct imports are forbidden.

### Slice-owned relationships trump DRY

- Relationship tables are owned by the slice that stores them.
- Shared helpers must not perform cross-slice writes.
- Cross-slice calls exchange **ULIDs + read-only snapshots only**.
- Duplicating small amounts of logic is acceptable (preferred) to preserve
  boundaries and avoid schema leakage.

---

## 2) Correlation and Observability (`request_id`)

- **Correlation is mandatory (`request_id`).**
  
  - `request_id` is a correlation ID, not a transaction/session handle.
  - DB scope is controlled by `db.session`, not by `request_id`.

- **One boundary invocation = one `request_id`.**
  
  - Generated at the boundary (route/CLI).
  - Passed downward to any services/emitters involved.

- **Propagate everywhere.**
  
  - Any Ledger/event/log record created because of that invocation MUST
    carry the same `request_id`.

- **Never generate `request_id` inside services.**
  
  - Missing `request_id` is a boundary bug.
  - Services may assert it exists, but must not mint a new one.

Purpose: make it trivial to reconstruct the full chain of effects for a single
action by filtering logs and Ledger on `request_id`.

---

## 3) Contracts & DTO Canon

### Contract rules

- **Contracts are versioned.** Add `*_v2` next to `*_v1`; never mutate `v1`.
- **Contracts are thin adapters.** Validate → call service → return DTO.
- **Errors are explicit.** Contracts raise contract-scoped errors; routes
  translate them to consistent UI/HTTP responses.
- **Contracts never return ORM models** or raw SA rows.

### DTO rules

DTOs are the only shapes allowed to cross slice boundaries.

Ownership and location:

- DTOs live in the owning slice: `app/slices/<slice>/mapper.py`.
- Callers must not import slice models; they consume contracts.

Default DTO type:

- Prefer `@dataclass(frozen=True, slots=True)` for stable DTOs.
- Use `TypedDict` only for intentionally dict-like blobs (reports, buckets,
  policy JSON passthrough).

Stability promise:

- Adding fields is OK (non-breaking).
- Removing/renaming fields is breaking → requires a new contract version.

Naming:

- Dataclasses: `*DTO` (e.g., `WizardStepDTO`, `EntityCardDTO`)
- TypedDict views: `*View` (e.g., `PersonView`, `OrgView`)

---

## 4) Slice-local Mappers (Uniform Projection Layer)

Every slice MUST have:

- `app/slices/<slice>/mapper.py`

Mappers are pure projection:

- no DB queries (inputs must already be loaded)
- no DB writes
- no commits/rollbacks
- no emits/Ledger
- no policy decisions

PII rule:

- Only the Entity slice may project PII (under strict rules).
- Other slices’ mappers must remain non-PII.

Services call mappers; contracts return mapper shapes; routes never serialize ORM
objects directly.

---

## 5) Lib-core (Shared Primitives)

`app/lib/` is VCDB “lib-core”: centralized, generic, non-PII primitives safe to
import anywhere.

Constraints:

- **No business logic.**
- **No PII.**
- **No slice dependencies.** `app/lib` must not import slice code.
- **No cross-slice DTOs/mappers.** Projections live in slice `mapper.py`.

Single-source-of-truth rule:

- If it’s generic and cross-slice, it belongs in `app/lib`
  (`chrono`, `ids`, `jsonutil`, `hashing`, `pagination`, `schema`,
   `request_ctx`, `utils`, etc.).

Import discipline:

- Import concrete modules directly; avoid re-export “barrels”.

---

## 6) Identity, Keys, and Facets

- **ULID everywhere.** One ULID from creation to archive; joins/refs/events
  use ULIDs.
- **Entity is the identity spine.** `entity_entity.ulid` is the canonical
  identity key for every person/org.
- **Facets are PK=FK by `entity_ulid`.**
  - `EntityPerson.entity_ulid`
  - `EntityOrg.entity_ulid`
  - `Customer.entity_ulid`
  - `Resource.entity_ulid`
  - `Sponsor.entity_ulid`
- **Cross-slice references anchor on `entity_ulid` only.**
  - No slice invents or depends on a secondary “slice ULID” as the identity
    anchor.

---

## 7) Ledger, Auditing, and “Nothing Happens in the Dark”

- **Ledger is the audit spine (not the money book).**
  
  - Records semantic events (no PII), links by ULID.
  - Finance remains authoritative for monetary facts.

- **Append-only.** Content-hashed chain; nothing deleted—only archived.

- **Every mutation is ledgered.**
  
  - Committed state changes emit a Ledger event with stable semantics.

- **No PII in Ledger or logs.**
  
  - Only ULIDs + semantic field names; never values.

- **Correlation is mandatory.**
  
  - All emits/logs/ledger entries carry the boundary `request_id`.

---

## 8) Financial Matters

- **Finance is the single source of truth for money facts (actuals).**
- **No shadow ledgers outside Finance.**
- Other slices may track **intent** only:
  - budgets, caps, estimates, approvals, reservations, planned spend
  - must be explicitly labeled as non-authoritative intent
- Other slices reference Finance truth by ULID; they do not duplicate amounts as
  “truth”.
- **Finance records money; Calendar orchestrates spending.**

---

## 9) Privacy & PII Boundary

- **No PII outside Entity** (except approved snapshot stores like History or
  notes vault).
- Sensitive fields are protected; non-Entity slices store anonymized facts keyed
  by ULID.
- Analytics/reporting tables store non-identifying enumerations only.

---

## 10) Governance, Policy, and “No Schema Leakage”

- **Policy is JSON-file canon.**
  
  - Governance policies live under `slices/governance/data/`.
  - Each policy has a schema and semantic validation in the loader.

- **Policy never names other slices’ tables/columns.**
  
  - Policy contains semantic hints, not schema.
  - Mapping happens in the target slice.

- **Admin editing is gated.**
  
  - Policy edits only via Admin slice, only when actor satisfies:
    **RBAC `admin` + domain role `governor`**.

- **Canonical state codes live in one place.**
  
  - Two-letter postal state codes are canon in `app/lib/geo.py`
    (the only exception to the policy-as-JSON rule).

Policy cohesion rule (prevents “giant JSON creep”):

> Policies are split by concept, not by slice. If a policy grows beyond one
> concept, split it and cross-reference via `meta.notes`. Never duplicate a
> concept across policies.

---

## 11) Timekeeping

- Persist in UTC; present local time in UI only.
- DB timestamps are naive UTC.
- `app/lib/chrono.py` is the single source of truth for time helpers.

---

## 12) Web Safety & Forms

- CSRF on every POST.
- Consistent form rendering; inline field errors.
- AuthZ at the route boundary; services assume authorized inputs.

---

## 13) Data Retention & Deletion

- Nothing is deleted. Data is archived per Governance retention schedules.
- State changes remain observable and auditable via the Ledger.

---

## 14) Testing & Development Discipline

- Tests reflect reality: prefer realistic route flows over bending services to
  tests.
- Cross-slice tests compose via contracts:
  Entity → facets → downstream ops → Ledger assertions (no PII).
- Deterministic seeds; tests run against migrated schema with known fixtures.

---

## 15) Slice Responsibilities (Provisional)

Ownership may evolve; ownership boundaries do not.

### Calendar (Projects / Tasks / Scheduling / Estimates)

- Owns work intent and schedules.
- May store estimates/plans (clearly labeled as intent).
- Must not store authoritative money facts (Finance owns actuals).
- References Finance truth by ULID.

### Governance (Policy / Constraints / Budget Rules)

- Owns policy, not implementation.
- Defines constraints, eligibility, caps, templates, budget-building rules.
- Contains semantic hints only; no schema leakage.
- Must not become an operational “facts” system.

### Sponsors (Fundraising / Donor CMS / Commitments)

- Owns fundraising and relationship management.
- May record commitments/intent (pledges, restrictions, earmarks).
- Must not maintain authoritative financial truth (Finance owns actuals).
- References Finance and Ledger by ULID for posted donations and audit events.

### Operational slices (Logistics / Resources / Customers)

- Own operational facts keyed by `entity_ulid`.
- Must not store PII outside Entity.
- Must not store authoritative money facts outside Finance.

---

## 16) Refactor Sequence (Guideline)

1. Entity (services → contracts → routes → tests)
2. Customer facet (services → contracts → routes → tests)
3. Resource facet (services → contracts → routes → tests)
4. Sponsor facet (services → contracts → routes → tests)
5. Downstream ops (Logistics/Finance integrations)
6. Cross-slice tests rebuild

---

## Addendum A — Entity Creation Wizard (Canon)

### A1) Creation Wizard is not the Edit Surface

- Wizard is a slice-local golden path to create a brand-new Entity in a
  minimally valid, editable state.
- Wizard flows are not part of the cross-slice contract surface.
  Cross-slice reads/edits go through versioned contracts; wizard stays internal
  to the owning slice.

### A2) PRG and Back/Refresh Defense are mandatory

- Every step is GET form → POST mutate → redirect (PRG).
- Every step POST is guarded by a per-step nonce stored in session:
  - nonce issued on GET
  - nonce verified on POST
  - nonce consumed on successful mutation
  - nonce preserved/reissued on validation errors
- Stale submits must not reach services (no flush, no Ledger spam). They redirect
  back into the deterministic wizard flow.

### A3) Single active wizard run per session

- After Step 1 creates the Entity ULID, store `wiz_active_entity_ulid`.
- Wizard Start resumes the active run by default.
- Starting a truly new run requires explicit reset (e.g., `?reset=1`).

### A4) Wizard Ledger rules

- Wizard services emit events with field names only (no PII values).
- Emit only on mutation:
  - created or `changed_fields` non-empty → flush + emit
  - no-op → no flush + no emit

### A5) Deterministic flow

- Wizard transitions are deterministic and computed by `wizard_next_step()`.
- `next_step` values are endpoint-qualified (e.g., `entity.wizard_role_get`).
- Optional hardening: step GET gating may redirect forward once progressed,
  unless explicitly allowed via Review page.

---

## Addendum B — POC Ownership (Canon)

- Org↔POC relationship tables live and mutate inside the owning org slice
  (Resources/Sponsors).
- Entity supplies only:
  - `person_entity_ulid`
  - minimal read-only “contact card” when needed
- Avoid cross-slice “manager DTOs” for relationship mutation; preserve slice
  ownership even at the cost of small duplication.

---

## Addendum C — Small, Durable “Stop Future Drift” Lines

- Wizard vs Edit separation is mandatory: creation wizard flows stabilize as a
  golden path; future mutations happen through edit pipelines.
- No stale POSTs: any POST that mutates data must be guarded by PRG + server
  nonce; stale submits never hit services.
- No-op quieting: emit events only when `changed_fields` is non-empty (create
  counts as change).
- Governance policies are cohesive by concept; split and cross-reference via
  `meta.notes`, never duplicate.

**RBAC is a small catalog + guardrail layer. Governance defines domain semantics.**
