# VCDB v2 — Readiness Punch List Framework

## Purpose

This punch list exists to bring VCDB v2 from **“close enough to proceed” MVP state** to a more disciplined, test-proven, operator-ready state.

This is **not** a general UI beautification effort.

This is a structured completion pass intended to:

- harden slice boundaries

- complete deferred workflow details

- formalize access control

- mature Admin into the controlled oversight surface

- bring operator-facing slices up toward the current **Sponsors slice** standard

---

# Maturity Targets

## Sponsors-Level Operator Maturity

A slice is considered operator-mature when it has:

- clear purpose and operator workflow

- thin routes / thick services

- stable forms, validation, and postback handling

- complete HTML surfaces for its intended users

- correct auth / RBAC / domain-role gating

- stable contract seams

- route/service/contract tests proving intended behavior

- no placeholder or half-wired surfaces in active use

## Infrastructure Oversight Maturity

A slice is considered infrastructure-mature when it has:

- clear non-public role in system architecture

- stable internal services and contracts

- correct Admin-only or Admin/Auditor-only access path

- read/edit/review surfaces exposed through Admin where appropriate

- complete validation and auditability

- tests proving contract and seam behavior

- no accidental “public” UI expectations

---

# System Classification

## A. Operator Workflow Slices

These are the slices where day-to-day operator UI belongs.

- Entity

- Customers

- Resources

- Sponsors

- Calendar

Goal:  
**clean, intuitive, operator-first workflows**

---

## B. Restricted Staff Workflow Slices

These are slices with limited internal workflow UI for gated operational use.

- Logistics

- selected internal operational views in Calendar / Customers if needed

Goal:  
**tightly gated staff operations with minimal exposed surface area**

---

## C. Infrastructure / Policy / Audit Slices

These are not intended to have broad operator-facing UI.

- Finance

- Ledger

- Governance

Goal:  
**stable services, stable contracts, stable semantics, Admin-mediated access**

---

## D. Control Surface Slice

This is the human access point for policy, audit, review, approval, and maintenance.

- Admin

Goal:  
**controlled oversight, maintenance, queueing, and review surface**

---

# Immediate Strategic Priorities

## 1. Access-Control Hardening

Access control is no longer a final sweep item.

It must now be handled **slice by slice** so it can be:

- exercised in real workflows

- verified at the route level

- validated in the test suite

- reflected properly in Admin oversight flows

### Punch list

- classify every route by intended audience:
  
  - public
  
  - authenticated operator
  
  - staff
  
  - admin
  
  - auditor
  
  - governor where applicable

- add missing route guards

- test allowed / denied access paths

- verify mutating routes are protected correctly

- verify Admin and Auditor separation where intended

---

## 2. Admin as Control Surface

Admin is not a side utility. It is the controlled lens through which infrastructure slices are viewed and operated.

### Admin must become the home for:

- Governance policy editing and validation

- Ledger audit / review / verification surfaces

- Finance review / reporting / audit surfaces

- unified review and approval queue

- diagnostics and maintenance operations

- exception handling and integrity follow-up

---

## 3. Typed Review Queue, Not Generic Messaging

Avoid a vague internal “messaging system.”

Use a **typed Admin work queue** instead.

### Queue item examples

- change request

- review request

- approval required

- override request

- policy conflict

- integrity warning

- audit finding

### Queue item requirements

Each item should be:

- typed

- attributable

- status-driven

- linked to owning slice/entity

- actionable through the owning slice contract

- ledger-aware when resolved

This avoids a hidden bottleneck and preserves slice ownership.

---

# Cross-Cutting Punch List

## Access Control

- audit every slice for missing guards

- standardize route protection

- test access by role

- stop treating protection as deferred polish

Priority:  
**highest**

---

## Route / Layout / Navigation Cleanup

- remove stale endpoint references from global layout

- align nav with current slice names and routes

- confirm layout usage is intentional and current

Priority:  
**high**

---

## Missing Template Sweep

- find every `render_template(...)`

- confirm target file exists

- either create or intentionally retire broken surfaces

Known examples:

- `customers/admin_inbox.html`

- `admin/policy_view.html`

Priority:  
**high**

---

## Forms / Validation Consistency

- replace placeholder form modules where real workflow entry exists

- normalize CSRF, inline errors, and invalid postback behavior

- make form handling predictable across slices

Priority:  
**high**

---

## Transaction Boundary Cleanup

- remove service-layer commits where canon says routes own transaction

- keep services business-focused

- test the intended transaction pattern where helpful

Priority:  
**high**

---

## Slice Boundary Enforcement

- remove direct cross-slice model reach-arounds

- use Extensions/contracts instead

- audit the tree for boundary violations

Priority:  
**high**

---

## Dead Scaffolding Cleanup

- remove backup/example/stray scaffold files from live app paths

- move notes into docs if they still matter

- leave active tree intentional and current

Priority:  
**medium**

---

## Shared Entity Display Standardization

- unify entity card/name display across slices

- define one canonical shape

- define one canonical rendering strategy

Priority:  
**high**

---

## Test Parity Across Slices

- bring each slice toward Sponsors-level proof

- include route tests, service tests, contract seam tests, and permission tests

Priority:  
**high**

---

# Slice Punch List

## Sponsors — Benchmark Slice

Role:  
**operator workflow benchmark**

Current state:  
best current example of end-to-end slice maturity

Punch list:

- clean up placeholder/form module ambiguity

- document as reference slice for future build standard

- capture the exact test and workflow pattern that makes it feel “proven”

Priority:  
**reference baseline**

---

## Entity

Role:  
**identity backbone / operator workflow foundation**

Shortcomings:

- needs Sponsors-level proof in tests

- route protection needs formalization

- entity card/display standard still unfinished

Punch list:

- test wizard end-to-end

- test nonce/replay protection

- define auth expectations

- finalize entity display contract

- treat as canonical identity surface

Priority:  
**high / early**

---

## Customers

Role:  
**operator-facing intake and casework workflow**

Shortcomings:

- admin inbox concept needs to migrate into Admin work queue thinking

- route protection needs hardening

- needs more proof at route/service level

- likely still has MVP-era rough edges

Punch list:

- remove or replace slice-local inbox concept

- route all approval/review work toward Admin queue architecture

- test intake, history, overview, and change flows

- add access control now

- standardize entity display usage

Priority:  
**high**

---

## Resources

Role:  
**operator-facing service/resource workflow**

Shortcomings:

- forms still immature

- good visible workflow, but not yet Sponsors-level proven

- access control needs formalization

Punch list:

- build real forms where operator entry exists

- test onboarding/detail/search/update flows

- harden route protection

- confirm stable DTO/read-model shapes for UI

Priority:  
**high**

---

## Calendar

Role:  
**operator workflow slice with funding-demand sub-area already maturing**

Shortcomings:

- funding-demand lane is stronger than general project/task UI

- broader UI maturity not yet uniform

Punch list:

- finish funding-demand lane to proven state

- decide what broader project/task UI is deferred

- test HTML/operator surfaces, not just service bridge logic

- keep scope disciplined

Priority:  
**medium-high**

---

## Logistics

Role:  
**restricted staff operations slice**

Shortcomings:

- should not be evaluated as a broad operator UI slice

- workflow boundaries still need to be clarified

- staff-only management surfaces need definition

Punch list:

- define staff inventory workflows:
  
  - receive
  
  - issue
  
  - transfer
  
  - stock review
  
  - SKU introduction

- separate internal contract-driven behavior from staff-facing UI

- add access control and tests

- build only the minimal gated UI that routine inventory management requires

Priority:  
**medium-high**

---

## Admin

Role:  
**control surface for oversight, approval, policy, audit, maintenance**

Shortcomings:

- not yet mature enough for the role it needs to play

- missing template(s)

- transaction-boundary cleanup needed

- work-queue architecture still unsettled

Punch list:

- mature Admin into the home for:
  
  - policy maintenance
  
  - audit review
  
  - financial oversight views
  
  - unified work queue
  
  - diagnostics / repair / maintenance

- replace half-baked inbox aggregation with typed queue architecture

- fix missing templates

- remove service commits

- add tests for review/approval/maintenance flows

Priority:  
**highest**

---

## Governance

Role:  
**infrastructure semantics slice, Admin-mediated**

Shortcomings:

- should not be treated as a public/operator UI slice

- Admin/Governance boundary needs to be made explicit

- example/scaffold residue should be removed

Punch list:

- keep Governance focused on:
  
  - policy semantics
  
  - validation
  
  - schema-backed configuration
  
  - stable contracts

- push human editing/maintenance through Admin

- add tests for schema/semantic validation and save flows

- remove stray example routes/files

Priority:  
**high, but mostly through Admin integration**

---

## Finance

Role:  
**money facts / infrastructure audit slice, Admin-mediated**

Shortcomings:

- not an operator UI target

- Admin-facing review/read surfaces need clearer shaping

- contract/boundary discipline still needs hardening in places

Punch list:

- treat Finance as infrastructure, not broad UI

- build Admin-facing read/review/report surfaces only where needed

- remove any direct cross-slice model reach-around

- test contract seams, money-state transitions, and Admin access paths

- define which read models Admin needs for oversight

Priority:  
**high, but through Admin and contracts**

---

## Ledger

Role:  
**PII-free audit ledger / infrastructure slice, Admin/Auditor-mediated**

Shortcomings:

- should not be judged by lack of public UI

- needs Admin/Auditor-facing oversight model instead

Punch list:

- keep Ledger non-public and infrastructure-only

- define Admin/Auditor-facing needs:
  
  - verify
  
  - inspect event summaries
  
  - audit review
  
  - integrity checks

- expose those through Admin, not Ledger-native operator UI

- add seam/integrity tests as needed

Priority:  
**medium-high, via Admin**

---

# Recommended Work Waves

## Wave 1 — Access and Surface Classification

- classify all slices and routes by intended audience

- document what is operator-facing, staff-only, admin-only, auditor-only, infrastructure-only

---

## Wave 2 — Access-Control Hardening

- implement route protections slice by slice

- add access tests slice by slice

- stop treating permissions as deferred work

---

## Wave 3 — Admin Control Surface Build-Out

- governance maintenance

- finance oversight

- ledger audit visibility

- typed review / approval queue

- diagnostics / maintenance utilities

---

## Wave 4 — Operator Slice Completion

Bring these toward Sponsors-level maturity:

- Entity

- Customers

- Resources

- Calendar funding-demand lane

---

## Wave 5 — Restricted Staff Workflow Completion

- Logistics

- any tightly gated operational flows not belonging in general operator UI

---

## Wave 6 — Infrastructure Oversight Completion

- Finance read models for Admin

- Ledger audit surfaces for Admin/Auditor

- Governance edit/validation/status surfaces through Admin

---

# Slice Acceptance Checklist

Use this against every slice when it comes up for cleanup.

## Operator Slice Acceptance

- purpose clearly defined

- operator workflow is end to end

- routes are thin

- services own business logic

- forms/validation are real and consistent

- templates exist and render cleanly

- auth/role guards are correct

- contracts/read models are stable enough for UI

- happy-path and failure-path tests exist

- permission tests exist

- no active placeholder/example residue remains

## Infrastructure Slice Acceptance

- role in system architecture is clearly defined

- no accidental broad operator/public UI exists

- access is routed through Admin where appropriate

- contracts are stable

- semantics/validation are proven

- auditability is preserved

- seam tests exist

- admin/auditor visibility model is clear

## Admin Slice Acceptance

- can serve as controlled oversight surface

- policy editing is validated and auditable

- review/approval queue is typed and actionable

- finance/ledger/governance oversight views are correctly gated

- diagnostics/maintenance flows are safe and tested

- transaction boundaries follow canon

- admin vs auditor access distinctions are enforced

---

# Revised Outlook

The project is not “behind” because Finance, Ledger, and Governance lack public UI.

Those slices are correctly **non-public by design**.

The real path forward is:

- **formalize access now**

- **mature Admin into the control surface**

- **replace generic inbox concepts with a typed review queue**

- **bring the true operator slices up to Sponsors-level**

That is a cleaner, more intentional path than trying to make every slice look equally UI-complete.

If you’d like, I can next turn this into a **compact one-page checklist version** for quick reference at the top of each slice thread.

---

Absolutely — here’s a **compact one-page version** you can reuse at the top of each slice thread.

---

# VCDB v2 — Slice Cleanup Quick Checklist

## Purpose

This thread is for bringing the **[SLICE NAME]** slice from  
**“MVP / close enough to proceed”** to **tested, intentional, role-correct maturity**.

This is **not** a styling pass.

This is a focused completion pass to:

- harden access control

- clean up deferred details

- confirm slice boundaries

- complete operator or Admin-facing workflow

- prove route / service / contract seams

- remove placeholder or half-wired behavior

---

# 1) Classify the Slice First

Choose one:

## Operator Workflow Slice

Examples:

- Entity

- Customers

- Resources

- Sponsors

- Calendar

Goal:  
**clean, intuitive, operator-first workflow**

## Restricted Staff Workflow Slice

Examples:

- Logistics

- selected gated operational tools

Goal:  
**minimal, tightly gated staff operations UI**

## Infrastructure Slice

Examples:

- Finance

- Ledger

- Governance

Goal:  
**stable services, stable semantics, Admin-mediated access**

## Admin Control Surface

Example:

- Admin

Goal:  
**oversight, approvals, audit, policy, diagnostics, maintenance**

---

# 2) First Questions to Answer

- What is this slice **for**?

- Who is the intended user?

- Should it have direct UI at all?

- Should access be:
  
  - operator
  
  - staff
  
  - admin
  
  - auditor
  
  - governor

- What belongs in this slice directly?

- What should instead surface through **Admin**?

- What seams must be proven before UI is trusted?

---

# 3) Immediate Hardening Checklist

## Access Control

- identify intended audience for every route

- add missing guards

- verify read vs mutate permissions

- add allowed / denied tests

## Route / Service Discipline

- routes stay thin

- services own business logic

- no service-layer commits unless intentionally excepted and documented

## Slice Boundaries

- no cross-slice table/model reach-arounds

- use contracts / extensions instead

- confirm read-model boundaries are clean

## Template / Layout Integrity

- every `render_template(...)` target exists

- no stale nav links

- no dead endpoints in layout/shell

## Forms / Validation

- real forms where real operator entry exists

- consistent CSRF and inline errors

- predictable invalid-post behavior

## Scaffolding Cleanup

- remove backup/example/placeholder files from active paths

- move notes to docs if still needed

## Test Proof

- route tests

- service tests

- contract seam tests

- permission tests

- happy path + failure path

---

# 4) Acceptance Standard by Slice Type

## Operator Slice — Done When:

- purpose is clear

- workflow is end to end

- forms and templates are real

- auth is correct

- contracts/read models are stable

- route/service/contract seams are tested

- no obvious placeholder residue remains

## Restricted Staff Slice — Done When:

- staff-only workflow is clearly defined

- UI surface is minimal and intentional

- access is tightly gated

- internal vs staff-facing behavior is clearly separated

- routine flows are tested

## Infrastructure Slice — Done When:

- no accidental public/operator UI exists

- semantics and contracts are stable

- Admin-mediated access path is clear

- validation and auditability are proven

- seam tests exist

## Admin Slice — Done When:

- policy, audit, review, and maintenance surfaces are clear

- access distinctions are enforced

- typed work queue exists where needed

- oversight flows are tested

- transaction boundaries follow canon

---

# 5) Special Rule for Admin / Review Work

Do **not** build vague inboxes or generic internal messaging.

Prefer a **typed Admin work queue**.

Queue items should be:

- typed

- attributable

- status-driven

- linked to owning slice/entity

- actionable through slice contracts

- auditable in Ledger when resolved

---

# 6) Thread Output Target

At the end of this slice thread, produce:

## A. Current State

- what is solid

- what is deferred

- what is broken

- what is intentionally non-public

## B. Punch List

Group into:

- safe to complete now

- should stabilize first

- postpone until later

## C. Acceptance Criteria

State exactly what “done” means for this slice.

## D. Test Expectations

List the route/service/contract/permission tests required to call it proven.

---

# 7) Priority Order for Most Slices

1. classify the slice correctly

2. lock down access control

3. clean route/service/boundary issues

4. fix missing templates/forms

5. prove workflow with tests

6. polish only after behavior is trustworthy

---

# 8) Short Closing Test

Before calling a slice “done,” ask:

- Is this slice exposing only the UI it is supposed to expose?

- Is the workflow clear for the intended user?

- Are the permissions real and tested?

- Are the service and contract seams trustworthy?

- Would building more UI now reduce confusion, or hide unfinished structure?

If the answer is not solidly “yes,” the slice still needs another pass.

---

## Ultra-compact thread opener

You can paste this at the top of a new slice thread:

> This thread is a focused cleanup pass for the **[SLICE NAME]** slice.  
> The goal is to move it from MVP / close-enough state to tested, intentional maturity.  
> Please evaluate it in terms of:
> 
> - slice classification
> 
> - access control
> 
> - workflow completeness
> 
> - route/service/contract discipline
> 
> - template/form completeness
> 
> - test proof
> 
> - what is safe to finish now vs what should stabilize first vs what should wait
> 
> Treat Sponsors as the operator-workflow benchmark, and Admin as the control-surface benchmark where applicable.

If you want, I can also turn this into a **fill-in-the-blank slice worksheet** with headings for Current State, Risks, Punch List, and Acceptance Criteria.
