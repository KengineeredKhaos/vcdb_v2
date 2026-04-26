# VCDB v2 — Ethos & Canon Invariants (Refactored)

These are the non-negotiable rules that keep VCDB v2 maintainable, auditable,
and safe. If a change conflicts with anything in this document, the change is
wrong and must be redesigned.

**Nothing happens in the dark. Nothing is deleted; only archived.**

## How this document relates to the others

This document is the canon.

- The **System Shape & Money Flow Guide** explains how the application is shaped
  and how the major slices work together in plain English.
- The **Access, Admin & Permissions Plan** captures control-surface and access
  planning.
- The **Project-wide TODO** file is the work queue and must not be treated as
  canon.

If any of those documents conflict with this one, this document wins.

---

## 1) Architectural rules

### Skinny routes, fat services

- Routes and CLI commands orchestrate: parse, authorize, call services,
  respond.
- Services own business logic: normalize, validate, read, write, and flush.
- Routes and CLI own transaction boundaries. Services may `flush()` but never
  `commit()` or `rollback()`.

### One boundary invocation = one transaction

A single HTTP request, UI action, or CLI command is one unit of work and one
transaction boundary.

### Mutating service guardrails

All mutating service commands must:

- accept required identifiers as keyword-only parameters
- fail fast on missing identifiers and correlation data
- never commit
- never emit on no-op
- use a real `actor_ulid` for system paths

### Slice ownership is non-negotiable

- Vertical slices own their own tables.
- Slices do not reach across slice boundaries with direct table or ORM access.
- Shared helpers must not perform cross-slice writes.

### Extensions is the only bridge

All inter-slice calls go through `extensions/contracts`. Contracts are the
integration surface. Direct cross-slice imports are forbidden.

### Slice-owned relationships trump DRY

Relationship tables live in the slice that owns them. Small amounts of
duplication are acceptable when they preserve slice boundaries and prevent
schema leakage.

---

## 2) Correlation, observability, and audit

### `request_id` is mandatory

`request_id` is a correlation ID generated at the route or CLI boundary and
passed downward through all work caused by that invocation.

Services must not mint `request_id` values. Missing `request_id` is a boundary
bug.

### Ledger is the audit spine

- Ledger records semantic events, not money truth.
- Ledger is append-only.
- No PII is allowed in Ledger or logs.
- All emitted records caused by one invocation carry the same `request_id`.

### Nothing happens in the dark

Ledger anomalies are expected operational events. Repairs are expected operational work. The failure is not that something broke; the failure would be letting it break invisibly, repairing it silently, or allowing backup/archive to certify an unreconciled truth state. All committed state changes must remain observable through ledger events,
logs, or other deliberate audit surfaces. Nothing is silently rewritten.

### Ledger Maintenance & Admin Alerts

Ledger creates Admin alerts only when Ledger needs human awareness, repair, or backup/archive intervention. Clean checks are recorded as evidence, not queued as work.

---

## 3) Contracts, DTOs, and mappers

### Contract rules

- Contracts are versioned. Add new versions beside old ones.
- Contracts are thin adapters: validate, call service, return DTO.
- Contracts raise explicit contract-scoped errors.
- Contracts never return ORM models or raw SQLAlchemy rows.

### DTO rules

DTOs are the only shapes allowed to cross slice boundaries.

- DTOs live in the owning slice’s `mapper.py`.
- Dataclasses are preferred for stable DTOs.
- Dict-like shapes are reserved for intentionally dict-like payloads.
- Adding fields is non-breaking. Removing or renaming fields is breaking.

### Mapper rules

Every slice has a slice-local `mapper.py`.

Mappers are pure projection:

- no queries
- no writes
- no commits or rollbacks
- no ledger emission
- no policy decisions

Only the Entity slice may project PII.

---

## 4) Shared core rules

`app/lib` is the shared non-PII core.

It may contain:

- time helpers
- IDs
- hashing
- pagination
- JSON helpers
- schema helpers
- request context helpers

It must not contain:

- business logic
- slice imports
- slice DTOs or mappers
- PII

`app/lib/chrono.py` is the single source of truth for time handling.

---

## 5) Identity, keys, and facets

- ULID is the canonical identity and join key from creation to archive.
- Entity is the identity spine.
- Facet tables are PK=FK on `entity_ulid`.
- Cross-slice references anchor on `entity_ulid` only.

No slice invents a second identity anchor for the same real-world thing.

---

## 6) Privacy and PII boundary

- PII belongs in Entity, except for explicitly approved snapshot stores such as
  history blobs or notes vaults.
- Non-Entity slices store anonymized facts keyed by ULID.
- Analytics and reporting tables store non-identifying enumerations only.

---

## 7) Governance, taxonomy, and policy

### Governance is the rulebook

Governance owns:

- policy JSON
- policy schemas
- semantic constraints
- approvals and control rules
- policy-backed thresholds and cadences

Governance does not own another slice’s schema or query logic.

### Taxonomy is slice-local

Slice-local taxonomy files define stable keys and enumerations used by that
slice. Taxonomy is not policy.

Taxonomy must not carry conditional logic, thresholds, or cross-slice query
assumptions.

### Slices interpret and enforce

A slice service is responsible for:

1. validating taxonomy values
2. consulting Governance when policy is required
3. writing state and snapshots where appropriate
4. emitting non-PII ledger events

### Policy editing

Governance policy editing is only through Admin, and only for actors who
satisfy the required access and authority conditions defined by canon and
policy.

---

## 8) Financial canon

### Finance is the single source of truth for money facts

Only Finance owns actual money truth:

- journal entries
- reserves
- encumbrances
- spend
- projections and reporting

Other slices may store intent, estimates, approvals, reservations, or
narrative context, but not authoritative money truth.

### Calendar owns work intent, not money truth

Calendar owns projects, tasks, budget development, funding demands, and
execution orchestration. Finance owns the book of record for reserves,
encumbrances, receipts, and spend.

### Sponsors owns intent and relationship work

Sponsors owns prospects, pledges, cultivation, donor metadata, and realized
support handoff into Finance. Sponsors does not do accounting mechanics.

### Governance owns semantic approval truth

Governance validates and approves the semantic package used to publish a
FundingDemand. Governance does not create the demand and does not do
accounting-line selection.

---

## 9) Calendar demand pipeline canon

The canonical demand pipeline is:

Project  
→ Task planning  
→ Budget Snapshot / Budget Lines  
→ Demand Draft  
→ Governance semantic review  
→ approved semantics returned to Calendar  
→ published FundingDemand  
→ Sponsors fulfillment work  
→ Finance recognition and availability truth  
→ Calendar execution against recognized support

### Pipeline invariants

- No published FundingDemand exists without a Demand Draft.
- No Demand Draft exists without a locked Budget Snapshot.
- No published FundingDemand exists without Governance-approved semantics.
- Locked Budget Snapshots are immutable.
- Demand Draft is the only pre-publish demand artifact.
- Published FundingDemand is the downstream-facing ask and does not revert to a
  draft.

### Published context canon

`FundingDemandContextDTO` is a publish-time, versioned snapshot assembled by
Calendar from Calendar facts plus Governance-approved semantics and stored on
the published demand. It is consumed by Sponsors and Finance as frozen context,
not as live policy and not as accounting truth.

---

## 10) Operations support / OpsFloat canon

Project remains the authoritative purpose anchor for any project-related
funding, reserve, encumbrance, spend, reimbursement, and closeout.

Operations may support a project only through explicit, auditable support
allocations tied to both `funding_demand_ulid` and `project_ulid`.

Allowed support modes:

- `ops-seed`
- `ops-backfill`
- `ops-bridge`

Rules:

- operations support is never implicit
- publication does not mean funded
- funded state is based on posted support facts
- repayment or replenishment rules must be explicit
- Ledger event names must make the temporary/support nature obvious
- petty cash is out of scope for OpsFloat

---

## 11) Access and control-surface canon

### RBAC gets you to the door

RBAC controls entry to a surface.

### Domain or governance authority controls certain decisions

Decision-heavy actions may require additional domain or governance authority
once the actor is already inside the correct surface.

Do not apply decision-gate concepts to every ordinary list/detail/edit path.

### Admin is the control surface

Admin is the consolidated triage, oversight, and launch surface for trusted
operators. Admin owns operator workflow and visibility, not the underlying
truth of other slices.

Admin must not become:

- a bypass around slice boundaries
- a junk drawer
- a global repair engine
- a second business layer

Slice owns truth. Admin owns operator view.

---

## 12) Web, forms, and safety

- CSRF protection is required on every POST.
- AuthZ happens at the route boundary.
- Services assume authorized inputs.
- Stale-submit and back-button defenses are mandatory for wizard flows.

---

## 13) Data retention and archive canon

Nothing is deleted in the ordinary sense. Records are archived according to
governed lifecycle rules.

Archive is not silent removal from hot storage.

A record class does not leave hot storage until its archive package has been:

- prepared
- copied
- verified

Admin is the operator control surface for archive status, failures, approvals,
and intervention. The owning slice remains responsible for record meaning and
archive batch semantics.

Cron executes governed lifecycle work but does not invent archive policy.

---

## 14) Testing and development discipline

- Prefer realistic flows over bending services to tests.
- Cross-slice tests should compose via contracts.
- Seeds and fixtures should be deterministic.
- The test suite is expected to exercise real persistence and cross-slice state,
  not just mocks and stubs.

---

## 15) Wizard canon

Wizard flows are creation-only golden paths.

- They are linear.
- They are guarded against stale submits and resubmits.
- They end at review/confirm and handoff.
- They are internal to the owning slice, not cross-slice contract surfaces.

Mutation-after-creation belongs to edit surfaces, not to the wizard.

---

## 16) Customer, Resource, and relationship canons

### Customers

Customer owns customer-domain state, workflow, servicing status, needs,
eligibility, profile facts, and customer-facing case history references. It
does not own canonical PII and it does not own governance authority.

### Resources

When a new Resource capability is added, it must be reflected both in the
taxonomy and in the matching matrix, or it must be explicitly excluded from
matching with a reason.

### Org-to-POC relationships

Org-to-POC relationship tables live inside the owning slice. Entity provides
identity and read-only cards, not mutation of those relationships.

---

## 17) Refactor sequencing guideline

The preferred order remains:

1. Entity
2. Customers
3. Resources
4. Logistics
5. Calendar
6. Governance
7. Sponsors
8. Finance
9. Ledger
10. Downstream operations and integrations
11. Cross-slice test rebuilds
12. Admin intervention if/when required
13. Auth security factors & route guards

This order may evolve, but slice ownership boundaries do not.
