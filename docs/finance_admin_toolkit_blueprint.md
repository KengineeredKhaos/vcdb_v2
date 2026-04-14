# Finance Admin Toolkit Blueprint

## Purpose

This document defines the conceptual blueprint for the **Admin Toolkit** that supports the Finance slice.

Its purpose is to guide future development of Admin repair and oversight tooling **without compromising the foundational accounting and audit guarantees already established in the system**.

This is not a generic maintenance toolkit. It is a narrowly scoped, explicitly governed, and fully auditable repair surface.

---

## Opening Doctrine

**Nothing happens in the dark.**

The Finance slice is foundational. Money truth must remain trustworthy, explainable, and reconstructable.

The Admin Toolkit exists to support **well-documented, legally justifiable corrective actions**. It must never become a hidden backdoor into accounting truth.

Think of the Admin Toolkit as:

- a **clean-room environment**
- visible through **thick safety glass**
- accessed only through **one narrow, guarded service port**
- where every operator **shows a badge, wipes their feet, and leaves a record**

No exceptions.

---

## Role Boundary

### Auditor

Auditor is **read-only**.

Auditor may:
- observe
- trace
- explain
- verify
- report

Auditor may **not**:
- mutate data
- trigger repairs
- initiate corrective actions
- override workflows

Auditor peeks behind the curtain. End of story.

### Admin

Admin is the system's only authorized **repair technician**.

Admin may perform **controlled corrective actions**, but only through explicit playbooks designed for that purpose.

Admin is **not** a generic superuser and is **not** permitted to improvise database maintenance.

---

## Non-Negotiable Constraints

The system must ensure that no one can:

- edit `Journal` amounts in place
- edit `JournalLine` amounts in place
- delete `Ledger` rows
- rewrite history so that a bad posting appears never to have happened
- perform silent or direct table edits through Admin UI workflows
- bypass the Ledger trail for any repair activity

A bad posting must remain visible as a historical fact.

Corrections must happen by:
- reversal
- compensating entry
- replay
- repost
- derived-data rebuild
- explicit workflow resolution

The original event remains part of the record. The corrective action becomes part of the record too.

---

## Foundational System Truths

The Admin Toolkit must respect these system truths:

- **Finance owns money truth**
- **Ledger owns audit truth**
- **Calendar originates funding and disbursement demands**
- **Sponsors realizes inbound funding against published demands**
- **Governance supplies semantic guidance and approval constraints**
- **`request_id` is the cross-slice correlation anchor**
- **services flush; Ledger emit happens after flush; routes commit**

The Admin Toolkit must never redefine or bypass these boundaries.

---

## What the Admin Toolkit Is

The Admin Toolkit is a set of **named, narrow, intentional repair playbooks**.

It should support only five classes of action:

1. **Observe**
   - inspect what happened
   - show related records by `request_id`
   - explain the trail

2. **Verify**
   - run integrity checks
   - detect mismatches or broken links
   - identify stuck or partial workflows

3. **Rebuild**
   - recompute derived data from source-of-truth records
   - refresh projections or reporting structures

4. **Compensate**
   - create reversing or offsetting records
   - repost correctly through approved service paths

5. **Resolve**
   - close a stuck workflow using an explicit, audited transition

---

## What the Admin Toolkit Is Not

The Admin Toolkit must never be:

- a SQL console in disguise
- a generic edit-anything maintenance panel
- a free-form journal editor
- a hidden bypass around Finance services
- a convenience tool for rewriting history
- a substitute for proper slice boundaries

If a task cannot be expressed as a named, reviewable, auditable playbook, it does not belong in the Admin Toolkit.

---

## Design Principles

### 1. Append-only repair philosophy

If accounting truth is wrong, repair by:
- reverse
- repost
- relink where lawful
- document the reason
- emit the repair trail

Do not erase the original mistake.

### 2. Derived data may be rebuilt

Derived data may be recomputed from source truth.

Examples:
- posting fact rebuild
- report rollup refresh
- traceability projection rebuild

These repairs are safer because they do not alter accounting truth.

### 3. Repairs must be explicit and named

Every repair capability must have:
- a clear name
- a narrow purpose
- a documented trigger condition
- a defined allowed operator role
- a deterministic implementation path
- a clearly documented Ledger story

### 4. Preview before commit

Every mutating Admin repair must support:
- preview / dry-run
- explanation of what will change
- operator reason entry
- final commit as a distinct step

### 5. Single service port

Repairs must enter through one controlled Admin repair surface and exit through standard slice service seams.

No side tunnels.

### 6. No hidden mutations

Every corrective action must leave:
- a domain truth effect where appropriate
- a Ledger trail
- a correlated `request_id`
- a human-readable reason

---

## Mandatory Repair Workflow Pattern

Every Admin repair playbook should follow this pattern:

1. **Locate** the target problem
2. **Explain** what is wrong
3. **Preview** the proposed repair
4. **Require** operator identity and reason
5. **Assign** a fresh repair `request_id`
6. **Perform** the corrective service action
7. **Flush** domain writes
8. **Emit** Ledger events
9. **Commit** only at the route boundary
10. **Display** the before/after trace

This pattern is mandatory.

---

## Required Audit Characteristics

Every Admin repair must answer these questions after the fact:

- Who performed the repair?
- Under what `request_id`?
- What exactly was wrong?
- What playbook was used?
- What records were touched?
- What corrective action occurred?
- What was the legal or operational justification?
- What new records were created?
- What old records remain as historical evidence?
- Can an Auditor explain the whole story without guessing?

If the answer to any of these is unclear, the repair design is insufficient.

---

## Initial Admin Toolkit Scope

The first Admin Toolkit for Finance should contain these capabilities.

### 1. Request Trace Explainer

Purpose:
- show the full cross-slice trail for a `request_id`

Must show:
- Calendar demand actions
- Sponsor fulfillment actions
- Finance journal/reserve/encumbrance/disbursement/op-float actions
- Ledger events
- related Admin issues or repair actions

Why first:
- understanding comes before repair

### 2. Integrity Sweep Dashboard

Purpose:
- identify suspicious conditions and queue them for Admin review

Examples:
- journal without posting fact
- posting fact without journal
- reserve or encumbrance missing required linkage
- disbursement without expected expense journal relationship
- grant rollup mismatch
- split workflow under inconsistent `request_id`s
- derived view drift

Why early:
- gives Admin a disciplined inbox of real problems

### 3. Derived Data Rebuild Tools

Purpose:
- rebuild safe, non-authoritative projections and report-support structures

Examples:
- rebuild posting facts
- rebuild grant accountability projections
- refresh reporting truth derived from journals and linked domain facts

Why early:
- low risk, high utility

### 4. Reverse and Repost Journal Wizard

Purpose:
- correct materially wrong money postings without erasing history

Flow:
- select target journal
- show trace and impact preview
- enter reason
- generate reversal
- optionally draft corrected repost
- commit as one repair workflow

Why essential:
- this is the heart of legitimate accounting repair

### 5. Workflow Resolver

Purpose:
- resolve stuck or partial orchestration states when money truth may be correct but workflow truth is not

Examples:
- retry reserve-on-receive step
- resolve failed handoff after a successful post
- close stale Admin issue after verified correction
- mark a workflow abandoned with explanation and trail

Why useful:
- prevents misuse of accounting repair tools for non-accounting problems

---

## Repair Categories and Rules

### A. Rebuild Repairs

Safe category.

Rules:
- may recompute derived data
- may not alter journal amounts or ledger history
- must be repeatable
- must be idempotent where feasible
- must emit a Ledger event indicating rebuild scope and result

### B. Linkage Repairs

Moderate risk category.

Rules:
- may repair lawful references between already-existing records
- may not alter the economic meaning of a posting
- must preserve previous broken state through audit trail
- must require preview and reason

### C. Compensating Financial Repairs

High risk category.

Rules:
- may create reversals and corrected reposts
- may never edit core journal amounts in place
- must visibly preserve the original mistake
- must use explicit Finance repair services, not generic Admin row editing
- should require stricter authorization and stronger audit detail

### D. Workflow Resolution Repairs

Controlled operational category.

Rules:
- may resume, retry, or close workflows
- may not rewrite accounting truth to make a workflow appear clean
- must clearly distinguish workflow repair from money repair

---

## Explicit Prohibitions for Future Development

Do not build:

- free-form journal editing screens
- generic "edit row" Finance maintenance views
- delete buttons for Ledger artifacts
- request-id rewrite tools
- direct table maintenance actions from Admin routes
- silent data-fix scripts exposed through the UI
- raw SQL execution surfaces

Any future need that appears to require these should be redesigned as a specific audited playbook instead.

---

## Required Technical Safeguards

Future implementation should include the following safeguards.

### Preview / Dry-run
Every mutating repair must support a preview mode.

### Reason required
Every repair must require a human-entered reason.

### Fresh repair request_id
Every repair workflow must receive its own repair `request_id`.

### Ledger all along the way
Repair stages must emit Ledger events that explain:
- issue detected
- repair initiated
- corrective action performed
- repair completed or failed

### Service-only mutation
Admin routes must call explicit slice services or repair contracts.
They must not perform direct table mutation.

### No commit in services
Services flush only.
Ledger emit after flush.
Route commits once.

### Role restriction
Auditor remains read-only.
Admin alone may perform repair playbooks.
Further narrowing by domain role or dual authorization may be added later.

---

## Success Criteria

The Admin Toolkit is successful only if it allows a future developer or operator to say:

- We can explain every money movement.
- We can detect when derived truth or workflow truth drifts.
- We can repair lawful mistakes without hiding them.
- We can reverse and repost without corrupting the trail.
- We can rebuild what is derived without touching what is authoritative.
- We can prove who did what, why, and when.
- We can show the whole story to an Auditor without embarrassment.

---

## Final Rule

The Admin Toolkit must never make the system *look* clean by hiding dirt.

It must keep the system **actually clean** by performing narrow, lawful, well-documented, fully audited corrective actions.

That is the blueprint.

