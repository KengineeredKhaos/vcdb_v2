# VCDB v2 — Access, Admin & Permissions Plan

This document pulls together the access-control and control-surface planning
notes that were previously mixed into Ethos.

This is a planning-and-structure document. Canon access rules still live in
the Ethos document.

---

## 1) Why this document exists

The access model has to represent two different things:

- **RBAC**: who may enter a surface
- **Decision authority**: who may make certain decisions once inside that
  surface

Those are not the same job and should not be collapsed into one giant table.

That is why this plan uses two levels:

1. a slice surface matrix
2. a function/action matrix

---

## 2) Ground rule

**RBAC gets you to the door.  
Authority decides whether you may make certain decisions once inside.**

Use decision gates only where there is a real approval, override, or controlled
action. Do not smear them across every ordinary list/detail/edit page.

---

## 3) Slice Surface Matrix

| Slice      | Surface Type          | Direct UI?            | Primary Access Path         | Entry RBAC               | Decision Domain Gate                          | Notes                             |
| ---------- | --------------------- | --------------------- | --------------------------- | ------------------------ | --------------------------------------------- | --------------------------------- |
| Entity     | Operator              | Yes                   | direct slice UI             | staff, admin, dev        | none or slice-specific staff rules            | identity backbone                 |
| Customers  | Operator              | Yes                   | direct slice UI             | staff, admin, dev        | staff; exceptional cases may require more     | intake and casework               |
| Resources  | Operator              | Yes                   | direct slice UI             | staff, admin, dev        | staff                                         | onboarding and management         |
| Sponsors   | Operator              | Yes                   | direct slice UI             | staff, admin, dev        | staff; policy-bound cases may require more    | cultivation and funding workflows |
| Calendar   | Operator              | Yes                   | direct slice UI             | staff, admin, dev        | staff; policy-bound cases may require more    | project and demand surfaces       |
| Logistics  | Staff-gated           | Limited               | direct slice UI + contracts | staff, admin, dev        | staff; controlled actions may require more    | inventory operations              |
| Finance    | Infrastructure-only   | No direct operator UI | Admin UI / contracts        | admin, auditor, dev      | authority only where policy-controlled        | money facts                       |
| Ledger     | Infrastructure-only   | No direct operator UI | Admin UI / contracts        | admin, auditor, dev      | none                                          | PII-free audit trail              |
| Governance | Infrastructure-only   | No general UI         | Admin UI / contracts        | admin, dev, auditor-read | authority required for policy change          | policy JSON semantics             |
| Admin      | Admin control surface | Yes                   | direct Admin UI             | admin, auditor, dev      | authority required for some policy/override   | oversight, queue, diagnostics     |

---

## 4) Function / Action Matrix template

Use this to plan real permission tests and route guards. Start with function
groups, not individual routes.

| Slice | Function Group | Human Surface? | Action Type | Entry RBAC | Authority Gate | Admin-Mediated? | Data Sensitivity | Test Requirement |
| ----- | -------------- | -------------- | ----------- | ---------- | -------------- | --------------- | ---------------- | ---------------- |

Suggested action types:

- read
- write
- approve
- override
- audit
- maintain

Suggested sensitivity buckets:

- public
- internal non-PII
- PII
- finance
- audit
- policy

---

## 5) Suggested first-wave function groups

### Governance

- policy view
- policy edit / save
- schema validation
- semantic validation
- policy diff / preview

### Ledger

- event review
- integrity checks
- audit reporting

### Finance

- finance report review
- reserve / encumbrance review
- reconciliation review
- exception review

### Customers

- intake create / update
- needs reassessment start
- exceptional review item handling

### Logistics

- stock adjustment
- reconciliation
- SKU introduction
- issuance controls

### Admin

- inbox item review
- queue status transitions
- dashboard and report access
- cron supervision
- launchpad actions

---

## 6) Admin mission and boundaries

Admin is the system control surface.

### Core principle

**Slice owns truth. Admin owns operator view.**

Admin may gather slice-owned, read-only DTOs and compose them into:

- dashboards
- inboxes
- reports
- anomaly summaries
- maintenance launch points

Admin does not own the meaning of another slice’s statuses, policies, or facts.

### What Admin is for

Admin helps trusted operators:

- detect problems
- summarize state
- prioritize work
- supervise maintenance and cron
- launch the correct owning-slice workflow

### What Admin owns

Admin owns the operator-facing workflow shell for maintenance-grade work,
including:

- dashboard
- unified admin inbox
- operational summaries
- diagnostics launch points
- cron and maintenance supervision
- policy workflow shell
- audit/report entry points

Admin may also own small amounts of local workflow state such as queue status
metadata or maintenance receipts.

### What Admin does not own

Admin does not own:

- another slice’s truth
- another slice’s semantics
- default cross-slice write authority
- universal repair logic
- convenience SQL reach-arounds

---

## 7) Admin feature map

### Dashboard

Purpose:

- quick operational pulse
- urgent issues
- slice-health visibility

### Unified inbox

Purpose:

- consolidated admin-facing review items
- no scattered “admin review required” islands

Important rule:

**No orphaned review flags.**

If a slice raises an Admin-facing review item, it must already define the
resolution path, valid actions, and resulting state transitions.

### Reports and audit views

Purpose:

- cross-slice read-only summaries
- anomaly and drift visibility
- recent ledger activity
- policy health and cron status

### Cron and maintenance supervision

Purpose:

- supervise recurring jobs
- acknowledge failures
- manually launch safe maintenance entry points where appropriate

### Policy workflow shell

Purpose:

- let Admin present, preview, validate, diff, and commit policy changes while
  Governance continues to own policy meaning and persistence

### Launchpad into owning-slice workflows

Purpose:

- get from triage to the correct owning-slice fix path without making Admin the
  universal fixer

---

## 8) Guardrails

Do not let Admin become:

- a bag of snakes
- a junk drawer
- a bypass around slice boundaries
- a second Governance slice
- a global repair engine

Admin should stay coherent, safe, and readable before it becomes ambitious.

---

## 9) Recommended build order

1. freeze Admin mission and boundaries
2. stand up the slice surface matrix
3. define first-wave function groups
4. map those groups to route guards
5. add permission tests
6. stand up the unified inbox shell
7. continue with broader reports and anomaly views

---

## 10) Open planning questions

These remain planning items, not settled canon:

- exact Admin vs Auditor read boundaries for every report surface
- which controlled actions require governance authority vs ordinary staff
- final route-by-route permission matrix
- whether some Logistics or Customer exception paths should be direct or
  Admin-mediated
