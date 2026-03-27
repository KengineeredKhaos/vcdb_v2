# VCDB Permissions Matrix Planning

Yes. I would build it as a **two-level matrix**, not one giant table.

Because with your clarified model, the matrix has to capture two different things:

- **RBAC** = who may enter a surface

- **domain role** = who may make certain decisions once inside that surface

Those are not the same job, and your policies already separate them. `policy_rbac` defines the RBAC role codes as `admin`, `auditor`, `dev`, `staff`, and `user`, while `policy_entity_roles` defines domain roles as `customer`, `resource`, `sponsor`, `governor`, `civilian`, and `staff`, with assignment rules like `admin -> governor/staff`, `auditor -> staff`, `staff -> staff`, and `user -> civilian`.

## My recommendation

Create:

### 1) a **Slice Surface Matrix**

One row per slice or major surface group.

This answers:

- is this slice operator-facing, staff-only, Admin-controlled, or infrastructure-only

- does it have direct UI

- who can enter it

- whether decision gates exist inside it

### 2) a **Function/Action Matrix**

One row per meaningful function group inside a slice.

This answers:

- who can view

- who can mutate

- who can approve or override

- whether the action is direct UI, Admin-mediated, or contract-only

- what tests you need

That keeps the first table readable and the second table actionable.

---

# Why not one giant matrix?

Because a single monster table becomes unusable fast.

You have several kinds of surfaces:

- direct operator workflows

- staff-gated workflows

- Admin/Auditor oversight surfaces

- infrastructure-only slices with no direct public/operator UI

- static reference surfaces

If you force all of that into one table, it becomes cluttered and you stop trusting it.

---

# Table 1 — Slice Surface Matrix

I would make this the top-level planning table.

## Suggested columns

| Slice | Surface Type | Direct UI? | Primary Access Path | Entry RBAC | Decision Domain Gate | Notes |
| ----- | ------------ | ---------- | ------------------- | ---------- | -------------------- | ----- |

## What each column means

**Slice**  
The slice name: Entity, Customers, Resources, Sponsors, Calendar, Logistics, Finance, Ledger, Governance, Admin.

**Surface Type**  
Use one of:

- Operator

- Staff-gated

- Admin control surface

- Infrastructure-only

- Static reference

**Direct UI?**

- Yes

- Limited

- No

- Admin-only

**Primary Access Path**  
How humans reach it:

- direct slice UI

- Admin UI

- no direct UI, contract-only

- static document library

**Entry RBAC**  
Who may enter the surface at all:

- user

- staff

- admin

- auditor

- dev

**Decision Domain Gate**  
Only use when needed:

- none

- staff

- governor

- staff or governor

This is where your clarification matters most:  
routine access and routine workflow entry are mostly RBAC questions; decision-heavy actions are where domain gates matter.

**Notes**  
Short clarifier like:

- “read-only reference docs”

- “policy edits only through Admin”

- “audit view only through Admin/Auditor”

- “routine inventory staff-only”

---

## Suggested starter rows

| Slice      | Surface Type          | Direct UI?            | Primary Access Path         | Entry RBAC                          | Decision Domain Gate                                     | Notes                             |
| ---------- | --------------------- | --------------------- | --------------------------- | ----------------------------------- | -------------------------------------------------------- | --------------------------------- |
| Entity     | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | none / staff for certain actions                         | identity backbone                 |
| Customers  | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff; governor for exceptional approvals if needed      | intake and casework               |
| Resources  | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff                                                    | onboarding and management         |
| Sponsors   | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff; governor where policy/override required           | cultivation and funding workflows |
| Calendar   | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff; governor on policy-bound decisions                | project/funding-demand surfaces   |
| Logistics  | Staff-gated           | Limited               | direct slice UI + contracts | staff, admin, dev                   | staff; governor/admin for exceptional controls if needed | inventory operations              |
| Finance    | Infrastructure-only   | No direct operator UI | Admin UI / contracts        | admin, auditor, dev                 | governor only where policy decision applies              | money facts                       |
| Ledger     | Infrastructure-only   | No direct operator UI | Admin UI / contracts        | admin, auditor, dev                 | none                                                     | PII-free audit trail              |
| Governance | Infrastructure-only   | No general UI         | Admin UI / contracts        | admin, dev; auditor maybe read-only | governor for policy changes                              | JSON policy semantics             |
| Admin      | Admin control surface | Yes                   | direct Admin UI             | admin, auditor, dev                 | governor for policy/override actions                     | oversight, queue, diagnostics     |

| Slice      | Surface Type          | Direct UI?            | Primary Access Path         | Entry RBAC                          | Decision Domain Gate                                     | Notes                             |
| ---------- | --------------------- | --------------------- | --------------------------- | ----------------------------------- | -------------------------------------------------------- | --------------------------------- |
| Entity     | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | none / staff for certain actions                         | identity backbone                 |
| Customers  | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff; governor for exceptional approvals if needed      | intake and casework               |
| Resources  | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff                                                    | onboarding and management         |
| Sponsors   | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff; governor where policy/override required           | cultivation and funding workflows |
| Calendar   | Operator              | Yes                   | direct slice UI             | staff, admin, dev                   | staff; governor on policy-bound decisions                | project/funding-demand surfaces   |
| Logistics  | Staff-gated           | Limited               | direct slice UI + contracts | staff, admin, dev                   | staff; governor/admin for exceptional controls if needed | inventory operations              |
| Finance    | Infrastructure-only   | No direct operator UI | Admin UI / contracts        | admin, auditor, dev                 | governor only where policy decision applies              | money facts                       |
| Ledger     | Infrastructure-only   | No direct operator UI | Admin UI / contracts        | admin, auditor, dev                 | none                                                     | PII-free audit trail              |
| Governance | Infrastructure-only   | No general UI         | Admin UI / contracts        | admin, dev; auditor maybe read-only | governor for policy changes                              | JSON policy semantics             |
| Admin      | Admin control surface | Yes                   | direct Admin UI             | admin, auditor, dev                 | governor for policy/override actions                     | oversight, queue, diagnostics     |

That table gives you the big picture fast.

---

# Table 2 — Function / Action Matrix

This is the real working table for Wave 1.

Do **not** start at individual routes. Start at **function groups**.

For example:

- search/list

- detail/view

- create

- edit

- publish

- approve

- override

- audit review

- maintenance

- static reference access

## Suggested columns

| Slice | Function Group | Human Surface? | Read/Write/Approve/Audit | Entry RBAC | Domain Gate | Admin-Mediated? | Data Sensitivity | Test Requirement |
| ----- | -------------- | -------------- | ------------------------ | ---------- | ----------- | --------------- | ---------------- | ---------------- |

## What each column means

**Slice**  
Which slice owns the function.

**Function Group**  
Human-meaningful action, not route name.  
Example: “Sponsor funding intent create/edit” or “Governance policy edit”.

**Human Surface?**

- direct

- admin

- none

**Read/Write/Approve/Audit**  
Choose one or more:

- read

- write

- approve

- override

- audit

- maintain

**Entry RBAC**  
Who can access the page or endpoint.

**Domain Gate**  
Who can actually perform the decision:

- none

- staff

- governor

- staff/governor

**Admin-Mediated?**

- yes

- no

**Data Sensitivity**  
Use broad buckets:

- public

- internal non-PII

- PII

- finance

- audit

- policy

**Test Requirement**  
What must be proven:

- allow/deny access

- happy path

- invalid input

- override denial

- audit read-only

- contract seam only

---

## Example rows

| Slice       | Function Group            | Human Surface?  | Read/Write/Approve/Audit | Entry RBAC                       | Domain Gate                      | Admin-Mediated? | Data Sensitivity | Test Requirement                                    |
| ----------- | ------------------------- | --------------- | ------------------------ | -------------------------------- | -------------------------------- | --------------- | ---------------- | --------------------------------------------------- |
| Governance  | policy view               | admin           | read                     | admin, auditor, dev              | none                             | yes             | policy           | allow/deny, read-only behavior                      |
| Governance  | policy edit/save          | admin           | write                    | admin, dev                       | governor                         | yes             | policy           | allow/deny, schema fail, semantic fail, audit event |
| Ledger      | event review              | admin           | audit                    | admin, auditor, dev              | none                             | yes             | audit            | allow/deny, read-only                               |
| Finance     | finance report review     | admin           | read/audit               | admin, auditor, dev              | none                             | yes             | finance          | allow/deny, correct scope                           |
| Customers   | intake create/update      | direct          | write                    | staff, admin, dev                | staff                            | no              | PII              | allow/deny, happy path, invalid input               |
| Customers   | exceptional review item   | admin           | approve                  | admin                            | governor or staff depending rule | yes             | PII/internal     | allow/deny, resolution audit                        |
| Logistics   | SKU introduction          | direct or admin | write/approve            | staff, admin, dev                | staff or governor if controlled  | maybe           | internal         | allow/deny, rule enforcement                        |
| Static refs | bylaws/articles/monthlies | direct          | read                     | user, staff, admin, auditor, dev | none                             | no              | public           | access only                                         |

That is the table that drives the actual hardening pass.

---

# Important design rule

Do **not** use domain roles everywhere.

Based on your explanation, I would use domain gates only for:

- policy decisions

- approvals

- overrides

- exceptional authorizations

- restricted staff/governor actions

I would **not** put `governor` or `staff` domain role columns on every ordinary list/detail/edit row unless there is an actual decision rule attached.

That keeps the matrix simple and faithful to your intent.

---

# A practical build order

## Step 1

Fill the **Slice Surface Matrix** first.

This should take one sitting.

Goal:  
classify every slice without getting lost in routes.

## Step 2

For Wave 1, build the **Function/Action Matrix** only for:

- Admin

- Governance

- Finance

- Ledger

- Customers

- Logistics

Why those first:

- Admin/Governance/Finance/Ledger define the control-surface model

- Customers/Logistics are where the tricky approval and internal workflow seams will show up quickly

## Step 3

Expand later to:

- Entity

- Resources

- Sponsors

- Calendar

Those are still important, but they are less conceptually confusing now.

## Step 4

Once the function matrix feels right, map it to:

- route guards

- contract seams

- permission tests

That is when it becomes executable work, not just planning.

---

# My strongest recommendation

Make this a **Markdown table in a project doc first**, not a spreadsheet.

Why:

- easier to version with the codebase

- easier to edit alongside slice notes

- easier to keep in the same language/style as the rest of VCDB docs

- easier to evolve before it becomes “official”

Once it stabilizes, then convert it to a spreadsheet if you want filtering.

---

# Minimal template to paste into your doc

## Slice Surface Matrix

| Slice      | Surface Type | Direct UI? | Primary Access Path | Entry RBAC | Decision Domain Gate | Notes |
| ---------- | ------------ | ---------- | ------------------- | ---------- | -------------------- | ----- |
| Entity     |              |            |                     |            |                      |       |
| Customers  |              |            |                     |            |                      |       |
| Resources  |              |            |                     |            |                      |       |
| Sponsors   |              |            |                     |            |                      |       |
| Calendar   |              |            |                     |            |                      |       |
| Logistics  |              |            |                     |            |                      |       |
| Finance    |              |            |                     |            |                      |       |
| Ledger     |              |            |                     |            |                      |       |
| Governance |              |            |                     |            |                      |       |
| Admin      |              |            |                     |            |                      |       |

## Function / Action Matrix

| Slice | Function Group | Human Surface? | Action Type | Entry RBAC | Domain Gate | Admin-Mediated? | Data Sensitivity | Test Requirement |
| ----- | -------------- | -------------- | ----------- | ---------- | ----------- | --------------- | ---------------- | ---------------- |
|       |                |                |             |            |             |                 |                  |                  |

The simplest rule of thumb is:

**RBAC gets you to the door.  
Domain role decides whether you may make certain decisions once inside.**

That distinction matches the policies and the architecture you described.
