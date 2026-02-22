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

---

### Ethos doc snippet: CustomerHistory admin tags

- **CustomerHistory entries are “enveloped” JSON blobs**: each `data_json` has a  
  uniform envelope containing human-friendly timeline fields (`title`,  
  `summary`, `public_tags`, `severity`, `happened_at`, `source_slice`,  
  `source_ref_ulid`) plus optional **silent** `admin_tags`.

- **Staff UI shows only the public envelope** (title/summary/public tags). It  
  never renders `admin_tags` and never records accusations—only operational  
  history and neutral signals.

- **Producers may set admin_tags**, but they do not “report” them. They simply  
  write the CustomerHistory entry.

- **Admin owns detection reporting**: a scheduled sweep (cron/systemd timer)  
  scans CustomerHistory for `has_admin_tags=true` and creates Admin-only alerts  
  (or tasks) for review. Sweeps are idempotent and cursor-based.

- **Cross-slice boundaries remain intact**: Customers never parses producer  
  payloads; producers own payload schemas; only the envelope is universally  
  understood.

---

### Golden Path (UI → DB → UI)

1. **Template/Form** collects or displays data (no rules, no DB).

2. **Route** orchestrates: auth, nonce/PRG, calls service, commit/rollback, emits  
   ledger on real changes.

3. **Service** owns business logic + DB reads/writes; returns DTOs; flushes only  
   when needed.

4. **Row DTO** = service-local projection of query results (DB → service).

5. **View DTO** = outward-facing shape for route/template/contract  
   (service → outside).

6. **Mapper** is pure translation (Row → View), no side effects.

Whenever you’re unsure where something belongs, ask:  
**Is this a decision? (service)** **Is this orchestration/audit? (route)**  
**Is this display? (template)** **Is this translation? (mapper/DTO)**

---

### Mutating service guardrails (canon)

All **mutating** service commands must:

- accept `entity_ulid`, `request_id`, and `actor_ulid` as **keyword-only**
  parameters
- call `ensure_entity_ulid()`, `ensure_request_id()`, and `ensure_actor_ulid()`
  at the top (fail fast)
- never commit (routes commit/rollback); services may `flush()` when needed
- never emit on no-op

System/automation paths must use a real `actor_ulid` (seeded system actor),
not `None`.

---

## Taxonomy vs Governance Policy (Canon Boundary)

VCDB v2 distinguishes **taxonomy/semantics** from **governance policy** to avoid
turning the Governance slice into a micro-management mill.

### Taxonomy (slice-local; code)

**Definition:** Stable keys, enums, and semantic groupings that define a slice’s
internal language (forms, validation, mapping, UI states). Taxonomy is owned by
the slice that uses it most and is stored as Python code (e.g.
`app/slices/<slice>/taxonomy.py`).

**Why code:** These values are referenced constantly, are tightly coupled to UI
and slice logic, and changing them usually requires a code deploy anyway. JSON

+ schema + contracts would add overhead without real operational benefit.

**Examples (slice-local taxonomy):**

- Customers: need category keys, tier groupings, allowed rating values, rank map
- Logistics: SKU part keys, warehouse/location key shapes, internal workflow states
- Finance: internal journal kinds, account type enums, posting workflow states
- Calendar: task kinds, project lifecycle states
- Resources: capability keys, readiness status enums, POC relation/scopes

**Rule:** If changing it requires a developer to update forms/templates/logic,
it is taxonomy → keep it slice-local.

### Governance Policy (cross-slice; JSON + schema + Admin-controlled)

**Definition:** Rules that define what is allowed, under what authority, and
under what limits—especially when the rule affects multiple slices or must be
editable without a code deploy.

Governance policies are stored as JSON under `app/slices/governance/data/`,
validated by JSON Schema + semantic checks, and editable only via Admin by a
user who satisfies BOTH:

- RBAC role `admin`
- domain role `governor`

**Examples (governance policy):**

- spending caps and countersignature rules (Finance + Sponsors + Admin)
- sponsor restrictions (vet-only/local-only) enforced by Logistics issuance
- cadence/eligibility rules that multiple slices must honor
- retention schedules and override policies
- SLA enforcement parameters when they impact cross-slice operations

**Rule:** If leadership might reasonably need to change it next week without a
deploy, and/or it affects more than one slice, it belongs in Governance.

### Middle-ground rule: Governance references taxonomy keys

Governance policy may **reference slice taxonomy keys by name**, but does not
own the full taxonomy lists.

- Taxonomy defines stable keys (e.g. `housing`, `employment`)
- Governance policy references those keys (e.g. reassess interval rules)
- The consuming slice interprets the policy using its local taxonomy

This preserves flexibility without duplicating taxonomies across Governance.

### Contract traffic minimization (implementation rule)

When a slice consumes Governance policy:

- load via a single read-only contract DTO (policy bundle)
- cache locally with TTL (or app-start cache with admin reload hook)
- do not call Governance repeatedly within one request

### Summary decision checklist

Before moving a value to Governance, ask:

1) Is this a leadership/authorization/compliance rule?
2) Does it affect more than one slice?
3) Is it likely to change without a deploy?
4) Does JSON+schema reduce risk more than it adds overhead?

**If “no” to (1) and (2), keep it as slice-local taxonomy.**

### Taxonomy file conventions (Canon)

These are IRL-world factors interpreted to code-world semantic labels. They bridge the gap between **code-world attributes** and **real-world facts.**

To keep slice-local taxonomy consistent and low-friction:

- **Location:** each slice owns a single module:
  - `app/slices/<slice_name>/taxonomy.py`
- **Scope:** taxonomy contains *names/keys/enums/groupings only* (no DB calls, no
  service logic, no contracts, no request context).
- **Naming:**
  - public constants use `UPPER_SNAKE_CASE`
  - keys stored in DB or JSON use **lower_snake_case** strings
  - groupings use tuples (stable order) or frozensets (membership checks)
- **Types:**
  - prefer tuples for deterministic iteration order (templates/tests)
  - use dict maps for rankings/labels (e.g., `RANK = {...}`)
  - keep values JSON-safe (str/int/bool), avoid custom objects
- **Stability:**
  - treat taxonomy keys as **public API** for the slice; changing a key is a
    breaking change
  - if a key must change, introduce an alias/migration layer (rare)
- **Validation usage:**
  - services validate inputs against taxonomy constants (fast fail)
  - forms populate SelectFields from taxonomy constants
- **No duplication:**
  - other slices must not copy or re-define another slice’s taxonomy
  - if cross-slice reference is needed, reference taxonomy **keys** (strings) in
    Governance policy, and let the owning slice interpret them
- **PII rule:** taxonomy never includes PII or user-entered values.
- **Docs:** each `taxonomy.py` begins with a short module docstring describing:
  - what the keys represent
  - whether keys are persisted in DB
  - any invariants (e.g., groupings cover all category keys)

---

Next
