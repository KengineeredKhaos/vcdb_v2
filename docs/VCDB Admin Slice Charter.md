# Admin Slice Charter

## Mission

**Admin is the control surface of VCDB v2.**  
It gives trusted operators a single place to observe system state, triage issues, supervise maintenance-grade operations, and launch the proper owning-slice workflow.

## Code Rule

**Slice owns truth. Admin owns operator view.**

**Owning slices retain authority over truth, semantics, validation,  
state transitions, and corrective commands.  
Admin is limited to observation, read-side composition, triage UX, and  
operator launch shells.**

**Where Admin presents a privileged action, the action must execute  
through the owning slice’s interface. Admin may frame, preview, and  
launch the workflow, but it must not absorb foreign business logic,  
foreign validation, foreign write semantics, or foreign audit meaning.**

## What Admin does

Admin may:

- compose read-only operator views from slice-owned projections

- present a unified inbox of Admin-facing issues

- summarize system health and notable activity

- supervise cron and maintenance runs

- host operator-facing workflow shells for privileged actions

- launch the proper owning-slice resolution path

- store small amounts of Admin-local metadata for triage/supervision

## What Admin does not do

Admin must not:

- own the truth of foreign slice data

- define or reinterpret foreign slice semantics

- perform direct cross-slice SQL reach-arounds as normal practice

- become a repair engine for other slices

- become a dumping ground for temporary logic

- absorb devtools leftovers

- host “misc maintenance” grab-bag behavior

- become a second business layer

## Anti-patterns

Admin must never become:

- a bag of snakes

- a universal fixer

- a bypass around slice boundaries

- a duplicate Governance/Auth/Ledger layer

- a convenience shortcut for breaking architecture

## Read side vs action side

### Read side

Admin reads and composes:

- dashboard summaries

- inbox items

- status boards

- anomaly cues

- operational reports

- maintenance receipts

### Action side

Admin may present operator workflow shells, but corrective meaning stays with the owning slice.

Examples:

- Auth owns unlock/reset/deactivate semantics

- Governance owns policy meaning, validation rules, and persistence semantics

- Ledger owns repair/integrity semantics

- Logistics owns reconcile/close semantics

Admin may initiate these through stable interfaces, but does not replace them.

## No orphaned review flags

This is a hard rule.

A slice may not generate an Admin-facing review item unless it already defines:

- issue type

- why it was raised

- allowed operator actions

- resulting state transitions

- audit behavior

- owning resolution route or command path

If the resolution path does not exist, the flag must not exist.

## Ownership model

### Admin truly owns

- Dashboard composition

- Unified inbox shell and its local metadata

- Cron supervision and maintenance supervision UI

- Operator-facing workflow shells

- Admin-local run receipts, acknowledgement markers, and queue-state metadata

- Cross-slice operational composition for read-only views

### Admin only surfaces

- Auth operator truth and commands

- Governance policy meaning and storage

- Ledger repair semantics

- Logistics reconciliation semantics

- Resource/Customer/Sponsor/Calendar/Finance issue semantics

- Foreign state transitions and foreign audit rules

## Contract posture

Admin should consume read-only slice-owned admin projections and compose them into operator-facing DTOs.

That means:

- slice-native contracts remain source of truth

- slice-owned admin projections remain slice-owned

- Admin composes read-only operator views

- corrective actions stay with the owning slice

## Definition of done

The Admin slice is “on mission” when:

- every page can be explained as observe, triage, supervise, or launch

- every foreign corrective action routes to an owning-slice command/workflow

- every inbox item has a real resolution path

- no Admin service commits transactions

- no cross-slice bypasses are hiding in convenience code

- the slice remains readable and purpose-focused

---

# Initial build scope

Do not build “all Admin.” Build the smallest useful control surface.

## Wave 1

This is the rebuild MVP.

### 1. Dashboard

Purpose: answer “what needs attention now?”

Initial contents:

- inbox counts by severity/type

- cron health summary

- policy health summary

- auth operator summary

- slice health cards

- recent critical activity summary

### 2. Unified Inbox shell

Purpose: answer “what exactly is waiting on Admin?”

Initial item shape:

- source_slice

- issue_kind

- severity

- summary

- opened_at_utc

- status

- resolution_route or launch descriptor

- small context payload

- allowed_actions summary

Admin owns inbox display/state.  
Owning slice owns issue meaning.

### 3. Cron & Maintenance Supervision

Purpose: answer “is the machine healthy?”

Initial features:

- jobs list

- last success / last failure

- stale run warning

- acknowledgement

- run receipts/history

- safe manual launch points where appropriate

### 4. Policy Workflow Surface

Purpose: answer “can an operator safely preview and process policy work?”

Admin owns:

- list

- preview

- diff

- validation display

- confirm/commit shell

Governance owns:

- policy meaning

- validation semantics

- persistence

- audit semantics

### 5. Auth Operator Management Surface

Purpose: answer “what is the operator state and how do I launch Auth-owned admin actions?”

Admin shows:

- operator list

- status summary

- auth maintenance cues

- launch points to Auth-owned commands

---

# Clean rebuild sequence

## Phase 1 — Canonize the charter

Pin the charter above as the slice constitution.

This is what protects the rebuild from drift.

## Phase 2 — Start a fresh slice skeleton

New Admin slice, clean-room.

Suggested structure:

```text
app/slices/admin/
    __init__.py
    routes.py
    services.py
    mapper.py
    contracts.py          # only if genuinely needed
    forms.py              # only if needed
    templates/admin/
        index.html
        inbox.html
        cron.html
        policy/
            index.html
            detail.html
            preview.html
        auth/
            operators.html
            operator_detail.html
    data/                 # only if Admin truly owns local config/state metadata
```

Keep it lean.

## Phase 3 — Define the first DTO/view shapes

Before pages sprawl, define the read models.

Suggested first-pass shapes:

- `DashboardDTO`

- `SliceHealthCardDTO`

- `InboxItemDTO`

- `InboxSummaryDTO`

- `CronJobStatusDTO`

- `PolicyHealthSummaryDTO`

- `AuthOperatorSummaryDTO`

These should be operator-facing, not truth-owning domain models.

## Phase 4 — Build dashboard first

That forces the slice to prove its mission early.

If the dashboard starts drifting toward repair logic, you will see it immediately.

## Phase 5 — Build inbox shell second

This is the center of gravity.

It enforces the no-orphaned-review-flags rule and becomes the operational triage heart.

## Phase 6 — Build cron supervision

A clean, truly Admin-native capability.

## Phase 7 — Build policy workflow shell

Admin owns operator experience, not policy truth.

## Phase 8 — Build Auth operator surface

Same shell pattern.

---

# Guardrails for implementation

## Route/service posture

- routes stay thin

- services compose/read

- services may flush but not commit

- routes own commit/rollback

## Data posture

- no foreign truth copied into Admin tables

- only Admin-local operational metadata may persist in Admin storage

- read models come from contracts/projections, not SQL scavenging

## Boundary posture

- no direct slice-to-slice reach-around “just this once”

- if Admin needs a foreign view, the owning slice must expose it properly

## UX posture

Every Admin page should answer one of these:

- what needs attention?

- what changed?

- what is unhealthy?

- what can I launch safely?

If a page cannot answer one of those, it probably does not belong in Admin.

---

# Immediate backlog

Here is the first practical backlog I would pin.

## A. Charter and architecture

1. Pin Admin charter

2. Pin no-orphaned-review-flags rule

3. Pin Admin ownership vs surfaced-only table

4. Pin Admin anti-patterns list

## B. New slice scaffold

1. Create fresh Admin blueprint

2. Create clean template/layout structure

3. Create mapper + DTO layer

4. Register blueprint only after minimal route health is green

## C. Dashboard MVP

1. Build `DashboardDTO`

2. Build slice health cards

3. Add inbox summary panel

4. Add cron summary panel

5. Add policy health panel

6. Add auth summary panel

## D. Inbox MVP

1. Define `InboxItemDTO`

2. Define minimum issue fields

3. Add list/filter/sort

4. Add item detail/launch view

5. Enforce resolution-path requirement

## E. Cron MVP

1. Job summary view

2. run receipt/history view

3. stale/failure cues

4. acknowledgement workflow

## F. Policy workflow MVP

1. policy index

2. policy detail

3. preview/validate/diff view

4. commit shell calling Governance-owned semantics

## G. Auth operator MVP

1. operator list

2. operator detail

3. launch points to Auth-owned actions

---

# One clarifying design rule worth pinning

I would add this sentence to the charter:

**Admin may own workflow shells for privileged operator actions, but the command semantics, validation rules, resulting state transitions, and audit meaning remain with the owning slice.**

That sentence keeps Policy and Auth from quietly sliding into Admin ownership.

---

# Recommended next artifact

The next thing to write is not code.

It is a short, pinned project note titled:

**“Admin Slice Charter and Rebuild Scope”**

That note should contain:

- mission

- boundaries

- non-goals

- no-orphaned-review-flags rule

- Wave 1 scope

- build sequence

That gives the rebuild a fixed compass before implementation starts.

I can draft that pinned note in project-doc style next.

---

# Admin slice build waves

## Wave 0 — Charter to scaffold

Goal: create a clean Admin slice shell that cannot drift on day one.

Build:

- fresh `admin` slice scaffold

- blueprint registration

- empty but live routes for:
  
  - dashboard
  
  - inbox
  
  - cron
  
  - policy index
  
  - auth operators

- `mapper.py`

- `services.py`

- minimal templates

- route tests / smoke tests

Rules locked in:

- no service commits

- no foreign SQL reach-arounds as habit

- no write semantics owned by Admin

- no orphaned review flags

Deliverable:

- Admin slice exists, loads, renders basic pages, and fits canon

Exit gate:

- all Admin pages are clearly read/triage/launch pages

- no placeholder “misc maintenance” junk drawer appears

---

## Wave 1 — Read-side backbone

Goal: define Admin’s real shape before page sprawl starts.

Build the first DTO/view layer:

- `DashboardDTO`

- `SliceHealthCardDTO`

- `InboxSummaryDTO`

- `InboxItemDTO`

- `CronJobStatusDTO`

- `PolicyHealthSummaryDTO`

- `AuthOperatorSummaryDTO`

Design rule:  
these are operator-facing read models, not domain truth models.

Also define where each comes from:

- slice-owned projections where needed

- Admin composition only on the read side

Deliverable:

- stable internal vocabulary for Admin pages

Exit gate:

- every Admin page can be described in terms of these DTOs

- no page reaches straight into foreign tables just to “get moving”

---

## Wave 2 — Dashboard

Goal: make the front door useful and safe.

Initial dashboard sections:

- inbox summary

- cron health

- policy health

- auth operator summary

- slice health cards

- recent critical activity summary

What it should answer:

- what needs attention now?

- what looks unhealthy?

- where should an operator go next?

Out of scope:

- direct repair buttons

- embedded foreign workflows

- giant analytics wall

Deliverable:

- coherent Admin home page

Exit gate:

- dashboard is useful without becoming a repair console

---

## Wave 3 — Unified Inbox shell

Goal: create the operational heart of Admin.

Minimum item shape:

- `source_slice`

- `issue_kind`

- `severity`

- `summary`

- `opened_at_utc`

- `status`

- `resolution_route`

- `allowed_actions_summary`

- small context payload

Admin owns:

- list/filter/sort

- item display

- queue metadata

- open/in_review/dismissed/escalated state

Owning slice owns:

- issue semantics

- valid actions

- state transitions

- audit meaning

Hard rule:  
an item cannot enter the Admin inbox unless the owning slice already has  
a real resolution path.

Deliverable:

- one clean queue, even if only a few slices feed it at first

Exit gate:

- zero orphaned review items

- every item leads somewhere real

---

## Wave 4 — Cron and maintenance supervision

Goal: give Admin one capability it truly owns.

Build:

- jobs list

- last success / last failure

- stale job detection

- acknowledgements

- run receipts/history

- safe manual launch points where appropriate

This is strong early Admin material because it is naturally operational,  
not semantic theft from another slice.

Deliverable:

- cron supervision page and related Admin-local metadata

Exit gate:

- Admin can supervise recurring system health without becoming devtools

---

## Wave 5 — Policy workflow shell

Goal: let operators safely work policy without making Admin the policy  
brain.

Admin owns:

- policy index

- policy detail display

- preview / diff / validation presentation

- confirm / commit shell

Governance owns:

- policy meaning

- validation semantics

- persistence

- resulting state changes

- audit meaning

This wave is important because it tests the Code Rule in practice.

Deliverable:

- operator-friendly policy workflow surface

Exit gate:

- Admin frames the workflow, Governance owns the action

---

## Wave 6 — Auth operator management surface

Goal: give trusted operators one place to inspect operator state and  
launch Auth-owned actions.

Build:

- operators list

- operator detail

- status summary

- launch points for Auth-owned privileged actions

Auth still owns:

- unlock/reset/deactivate semantics

- validation

- authorization

- persistence

- audit meaning

Deliverable:

- clean Auth operator launch surface in Admin

Exit gate:

- Admin does not quietly absorb Auth business logic

---

## Wave 7 — Audit and operational reports

Goal: broaden visibility after the core control surface is stable.

Start with:

- recent ledger activity summary

- queue aging report

- policy health/drift report

- cron run report

- slice anomaly summary

This is read-only composition, not system repair.

Deliverable:

- report pages that help operators spot patterns

Exit gate:

- reports remain observational

- no report page grows secret write-side behavior

---

## Wave 8 — Additional slice integrations

Goal: onboard other slices into the Admin control surface one at a time.

Candidates:

- Resources review items

- Logistics reconcile exceptions

- Ledger anomaly summaries

- Calendar operational exceptions

- Finance exception summaries

- Customers/Sponsors only where a real Admin-facing review path exists

Rule:  
integrate slices only when their issue types and resolution paths are  
already defined.

Deliverable:

- Admin grows by disciplined intake, not by dumping features into it

Exit gate:

- each new integration passes the no-orphaned-review-flags rule

---

# Recommended order of actual work

I would do it in this sequence:

1. Wave 0 — scaffold

2. Wave 1 — DTO/read backbone

3. Wave 2 — dashboard

4. Wave 3 — inbox shell

5. Wave 4 — cron supervision

6. Wave 5 — policy workflow shell

7. Wave 6 — auth operator surface

8. Wave 7 — reports

9. Wave 8 — additional slice integrations

That order gives you:

- identity first

- backbone second

- front door third

- queue center next

- then real operator rooms

---

# What to leave out until proven necessary

Do not let these sneak in early:

- Ledger repair UI

- generic “maintenance tools”

- diagnostics junk drawer

- direct DB utilities

- catch-all admin actions page

- slice-specific fixes reimplemented in Admin

If any of those are ever added later, they should arrive through a named,  
bounded workflow with clear ownership.

---

# Suggested file scaffold for Wave 0

Given your project style, I’d start here:

```text
app/slices/admin/
    __init__.py
    routes.py
    services.py
    mapper.py
    forms.py              # only if needed immediately
    templates/admin/
        index.html
        inbox.html
        cron.html
        policy/
            index.html
            detail.html
            preview.html
        auth/
            operators.html
            operator_detail.html
    tests/
        test_admin_routes.py
        test_admin_dashboard.py
        test_admin_inbox.py
```

I would avoid creating contracts until there is a clear need for a  
versioned Admin-facing interface.

---

# Guardrails to pin to the work

For every Admin feature, ask four questions:

1. Is this observation, triage, supervision, or launch?

2. Does another slice own the semantics?

3. Is Admin composing a read model, or stealing business logic?

4. If this is an inbox item, does a real resolution path already exist?

If a feature fails those checks, it probably does not belong in Admin.

---

# My recommendation for the first build sprint

Start with just this:

### Sprint A

- fresh scaffold

- minimal routes

- minimal templates

- DTO skeletons

- dashboard page with stubbed sections

- tests proving the slice loads cleanly

### Sprint B

- inbox model and shell

- one or two real issue sources only

- status/filter/sort

- resolution route links

### Sprint C

- cron supervision

- policy workflow shell

That is enough to make Admin real without overbuilding it.

The cleanest next move is to draft the Wave 0 and Wave 1 backlog as an  
implementation checklist so you can start cutting files in a controlled  
way.
