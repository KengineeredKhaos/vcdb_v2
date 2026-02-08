# VCDB v2 — Ethos & Canon Invariants

These are the non‑negotiable rules that keep VCDB v2 maintainable, auditable, and safe. If a change conflicts with any item below, the change is **wrong by definition** and must be redesigned.

**Nothing happens in the dark!**

---

## 1) Architecture & Slice Boundaries

- **Skinny routes, fat services.** Routes orchestrate  
  (parse/authorize/respond); services hold business logic.
  
  - **Routes own the transaction scope.**  
    Routes own `commit/rollback` and error boundaries.  
    Contracts/services never create or pass sessions; they only use the  
    scoped `db.session` and may flush. A commit at the route boundary  
    commits all flushed work across all slices involved.
  
  - **Services flush only.**  
    Services may `flush()` but never `commit()` or `rollback()`.

- **Correlation is mandatory (`request_id`).**
  
  - **`request_id` is a correlation ID, not a transaction/session handle.**  
    It does not control database scope; `db.session` does.
  
  - **One boundary invocation = one `request_id`.**  
    A single UI action / HTTP request / CLI command generates exactly one  
    `request_id` at the boundary and passes it downward.
  
  - **Propagate everywhere.**  
    Contracts accept `request_id` and pass it to services (and/or  
    `event_bus.emit`). All ledger/events/log records created because of  
    that invocation MUST carry the same `request_id`.
  
  - **Never generate `request_id` inside services.**  
    Missing `request_id` is a boundary bug. Services may assert it is  
    present, but must not mint new ones.
  
  - **Purpose:** make it trivial to reconstruct and audit the full chain of  
    effects for one action by filtering logs and Ledger on `request_id`.

- **Vertical slices own their data.** Each slice reads/writes only its own  
  tables; no cross-slice DB reach-arounds.

- **No cross-slice imports.** Slices communicate only via the Extensions  
  integration surface.

- **Extensions is the only bridge.** All inter-slice calls go through  
  `extensions/contracts` (facades), not direct imports.

### Slice-local mappers (uniform projection layer)

- **Every slice MUST include a mapper module at a uniform location:**
  
  - `app/slices/<slice_name>/mapper.py`

- **Purpose:** mappers are the canonical home for projection code — turning  
  slice-owned ORM rows into safe, typed, ready-to-eat view/summary shapes  
  for UI/JSON/contract responses.

- **Mappers are pure:**
  
  - no DB queries (assumes inputs are already loaded; do not trigger  
    lazy-loads)
  
  - no DB writes
  
  - no commits/rollbacks
  
  - no event/Ledger emits
  
  - no policy decisions (only formatting/projection/redaction)

- **Slice boundary rule:** mappers are slice-local (not `app/lib`). No  
  cross-slice imports. Cross-slice reuse happens via contracts + DTOs, not  
  by importing another slice’s mapper.

- **PII boundary rule:** only the Entity slice may project PII fields under  
  its rules. Other slices’ mappers must remain non-PII.

- **Naming conventions (uniform across slices):**
  
  - DTO/view types: `*DTO` or `*View`  
    (e.g., `PartyDisplayDTO`, `CustomerSummaryView`)
  
  - mapping functions: `map_*` (e.g., `map_party_display(...)`)
  
  - private helpers: `_map_*` / `_format_*` / `_pick_*`

- **Services call mappers; contracts return mapper shapes.** Keep business  
  logic in services; keep shaping/formatting in `mapper.py`.

### Lib-core (shared library primitives)

- **`app/lib/` is VCDB “lib-core”:** centralized, generic, non-PII building  
  blocks that are safe and widely reusable across all slices.

- **Purpose:** provide small, stable primitives (IDs, time, hashing, JSON  
  determinism, pagination, schema validation, request context, logging  
  helpers, generic normalization/validation, etc.) so slices do not  
  duplicate low-level plumbing.

- **Non-negotiable constraints:**
  
  - **No business logic.** `app/lib` contains primitives and guardrails, not  
    domain workflows.
  
  - **No PII.** Nothing in `app/lib` should embed, infer, or expose PII; it  
    must be safe to import anywhere.
  
  - **No slice dependencies.** `app/lib` MUST NOT import slice code. Slices  
    may import `app.lib.*`, never the reverse.
  
  - **No cross-slice DTOs/mappers.** Projection/mapping belongs in  
    slice-local `app/slices/<slice>/mapper.py`. `app/lib` is not a  
    presentation layer.
  
  - **Stable APIs are canon.** Treat public functions/mixins in `app/lib` as  
    foundational: change only with explicit approval and a clear migration  
    plan.

- **Import discipline:** import concrete modules directly (no re-export  
  barrel pattern). Keep dependencies explicit to avoid circular imports.
  
  - Example: `from app.lib.ids import new_ulid` (not `from app.lib import *`)

- **Before adding a helper, check `app/lib` first.** If it’s generic and  
  non-PII, extend `app/lib`; if it’s slice-semantic or a projection, keep it  
  in the slice (`mapper.py` / services).

- **Single-source-of-truth rule:** if a primitive is cross-slice and  
  generic, it lives in `app/lib` (e.g., `chrono`, `ids`, `jsonutil`,  
  `hashing`, `pagination`, `schema`, `request_ctx`, `utils`). Do not  
  reimplement the same primitive inside slices.

### Architecture Uniformity — Enforcement Checklist

Use this checklist during refactors and code review. If an item fails, the  
change is not canon-compliant.

#### Boundaries & Imports

- No slice imports another slice (directly or indirectly). Cross-slice  
  calls go through `extensions/contracts` only.

- `app/lib/*` does not import any slice code. Slices may import  
  `app.lib.*`, never the reverse.

- No ORM models cross slice boundaries (only DTOs/primitive types cross  
  contracts).

#### Transactions & Side Effects

- Services are flush-only (no `commit()` / `rollback()` anywhere in  
  `services/*`).

- Routes/CLI own `commit/rollback` and error boundaries (single  
  consistent transaction pattern per request).

- Each boundary invocation creates exactly one `request_id`, propagates  
  it through contracts/services, and records it on all emits/logs/ledger  
  entries created by that invocation.

- Ledger/event emits occur only at the approved layer (per current canon:  
  route or explicitly designated command service), and never include PII.

#### Mapper Layer

- Slice has `app/slices/<slice>/mapper.py` and it contains projection  
  logic + typed view/DTO shapes.

- Mappers do not run DB queries or cause side effects (no writes, no  
  commits, no emits).

- Services call mappers; contracts return mapper/DTO shapes; routes never  
  serialize ORM objects directly.

#### Naming & Identity

- Identity is always `entity_ulid` (facet PK=FK). No “slice ULID” used as  
  an identity anchor.

- Function signatures use explicit names (`entity_ulid`, `request_id`,  
  `actor_ulid`) and avoid ambiguous variables like `ent` for multiple  
  meanings.

#### PII Discipline

- No PII outside the Entity slice (except approved snapshot stores). No  
  PII in logs/Ledger.

- Entity mappers/projectors return only the minimum allowed  
  display/contact fields for the caller’s need (least-privilege).

#### Pagination & Shapes

- Paginated reads use the shared pagination primitive (`Page` /  
  `paginate_sa`) and return a consistent page shape.

- Query functions return typed view/DTO shapes (TypedDict/dataclass DTO),  
  not raw dicts or ORM objects.

#### Before Adding Code

- If you need a generic helper: check `app/lib` first; if it’s generic +  
  non-PII, put it there.

- If you need a projection: put it in the slice’s `mapper.py`.

- If you need business logic: put it in `services/*` (queries vs  
  commands), not in contracts/routes.



---

## 2) Contracts & DTOs

- **Contracts are versioned.** Add `v2` next to `v1`; never mutate `v1` in place.
- **Contracts are thin adapters.** Contracts do: **validate → call service → return DTO**.
- **DTOs at the boundary.** Cross-slice inputs/outputs are typed DTOs (and validated where applicable).
- **Errors are explicit.** Contracts raise contract-scoped errors; routes translate them to consistent responses.

---

## 3) Identity, Keys, and Facets

- **ULID everywhere.** One ULID from creation to archive; all joins, refs, and events use ULIDs.
- **Entity is the identity spine.** `entity_entity.ulid` is the canonical identity key for every person/org.
- **Facets are keyed by `entity_ulid` (PK=FK).** Facet tables use **PK=FK → `entity_entity.ulid`**:
  - `EntityPerson.entity_ulid`
  - `EntityOrg.entity_ulid`
  - `Customer.entity_ulid`
  - `Resource.entity_ulid`
  - `Sponsor.entity_ulid`
- **Slice-to-slice references anchor on `entity_ulid` only.** No slice invents or depends on a secondary “slice ULID” as an identity key.

---

## 4) Ledger, Auditing, and Observability

- **Ledger is the audit spine, not the money book.** Ledger records semantic events (no PII) and links by ULID; Finance remains the authoritative source for monetary facts.
- **Ledger is Append‑only.** Nothing happens in the dark. Content‑hashed chain; events cross‑link to domain records by ULID. Nothing is deleted, only archived.
- **Every mutation is ledgered.** All committed state changes emit a Ledger event with stable semantics.
- **No PII in Ledger or logs.** Ledger/logging stores **ULIDs + semantic field names only**, never values.
- **Correlation is mandatory.** Routes pass `request_id`/correlation IDs through services and into Ledger events.

---

## 5) Financial Matters

- **Finance is the Single Source of Truth for money facts (actuals).** All authoritative monetary amounts, balances, journal entries, and account/fund semantics originate in (or are recorded by) the Finance slice.
- **No shadow ledgers outside Finance.** If a persisted amount could be mistaken for an authoritative financial figure, it belongs in Finance.
- **Other slices may track money intent only.** Budgets, caps, estimates, approvals, reservations, and “planned spend” may live outside Finance, but must be explicitly labeled as non-authoritative intent.
- **Other slices reference financial facts via ULIDs and semantics.** When a non-Finance slice needs to point at an actual money movement, it stores a reference ULID to the Finance record (not a duplicate amount as “truth”).
- **Finance records money; Calendar orchestrates spending.** Calendar can schedule and approve work that implies spending, but the only authoritative record of money movement (income/expense/transfer) is the Finance journal.

---

## 6) Privacy & PII Boundary

- **No PII outside Entity.** PII lives only in the Entity slice (and strictly controlled snapshot stores like `CustomerHistory` / notes vault).
- **Encrypt sensitive fields.** PII is field‑level protected; non‑Entity slices store anonymized facts keyed by ULID.
- **Analytics are non-identifying.** Reporting/analytics tables store plaintext enumerations only (no identifying data).

---

## 7) Governance, Policy, and “No Schema Leakage”

- **Policy is JSON‑file canon.** Governance policies are stored as JSON under `slices/governance/data/` (single source of truth).
- **Policy never names other slices’ tables/columns.** Policies contain **semantic hints**, not schema; mapping happens in the target slice.
- **Schemas + semantic validation.** Every policy file has JSON Schema validation plus semantic checks in the loader pipeline.
- **Admin editing is gated.** Policy edits are only via the Admin slice and only when the actor satisfies **RBAC `admin` + domain role `governor`**.
- **Canonical state codes live in one place.** Two‑letter postal state codes are canon in `app/lib/geo.py` (only exception to the policy‑as‑JSON rule).

---

## 8) Timekeeping

- **Time = UTC.** Persist in UTC; present local time in the UI only.
- **DB timestamps are naive UTC.** Use naive UTC for DB `DateTime` fields.
- **`app/lib/chrono.py` is the single source of truth.** Any time helpers/aliases belong there (and nowhere else).

---

## 9) Web Safety & Forms

- **CSRF on every POST.** All POST forms include CSRF by default.
- **Consistent form rendering.** Use the namespaced macro import pattern and show inline field errors.
- **AuthZ at the route boundary.** RBAC decorators live at routes; services assume authorized inputs.

---

## 10) Data Retention & Deletion

- **Nothing is deleted.** Data is archived per Governance retention schedules.
- **Nothing happens in the dark.** State changes are observable and auditable via the Ledger.

---

## 11) Testing & Development Discipline

- **Tests reflect reality.** Prefer realistic route flows over bending services to tests.
- **Cross-slice tests compose via contracts.** Compose: Entity → facets → downstream ops → Ledger assertions (no PII).
- **Deterministic seeds.** Seeds are stable and reproducible; tests run against migrated schema with known fixtures.

---

## Unda Konstruktion

## X) Slice Responsibilities & Boundaries (Provisional)

These boundaries define ownership and prevent “shadow systems.” Details may evolve, but ownership does not.

### Calendar (Projects / Tasks / Scheduling / Estimates)

- **Calendar owns work intent and schedules.** Projects, tasks, assignments, and time coordination live here.
- **Calendar may store estimates and plans** (cost estimates, rough budgets, planned spend), clearly labeled as non-authoritative.
- **Calendar must not store authoritative money facts** (actual spend, balances, journal truth). Actuals are recorded in Finance.
- **Calendar references financial truth by ULID** when it needs to point to posted/real money movements.

### Governance (Policy / Constraints / Budget Rules)

- **Governance owns policy, not implementation.** It defines constraints, eligibility, caps, templates, and budget-building rules.
- **Governance policy contains semantic hints only** and must not reference other slices’ tables/columns (“no schema leakage”).
- **Governance must not be a ledger.** It defines rules; it does not record operational “facts” as authoritative truth.

### Sponsors (Fundraising / Donor CMS / Commitments)

- **Sponsors owns fundraising and relationship management.** Donors, pledges, acknowledgements, comms, and sponsorship metadata live here.
- **Sponsors may record commitments and intent** (pledges, restrictions, earmarks) as non-authoritative until posted as money facts.
- **Sponsors must not maintain authoritative financial truth.** Real money movement and balances are recorded in Finance.
- **Sponsors references Finance and Ledger by ULID** for posted donations, disbursements, and audit events.

### Logistics / Resources / Customers (Operational Facts, Not PII / Not Money Truth)

- **Operational slices own operational facts** (inventory movements, service fulfillment, customer-facing operations) keyed by `entity_ulid`.
- **They must not store PII outside Entity** and must not store authoritative money facts outside Finance.

## Refactor Sequence:

Do it in this exact order:

1. **Entity** (services → contracts → routes → tests)

2. **Customer facet** (S → C → R → T)

3. **Resource facet** (S → C → R → T)

4. **Sponsor facet** (S → C → R → T)

5. **Downstream ops** (Logistics/Finance integrations)

6. **Cross-slice tests** rebuild
