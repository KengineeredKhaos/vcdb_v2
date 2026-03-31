Good. Here’s the wave map I’d use.

# Admin rebuild waves

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

## Update @ 03/30/26

Quite a bit is now behind us.

My read is:

## Essentially in place

### Wave 0 — scaffold

Done enough.

### Wave 1 — DTO/read backbone

Done enough for Admin’s current needs.

### Wave 2 — dashboard

Baseline done. Admin has a real home surface now.

### Wave 3 — inbox shell

Done enough. The inbox seam exists and cron can escalate into it.

### Wave 4 — cron supervision

Baseline done.  
You now have:

- runner

- lock/run history

- CLI

- Admin cron page

- `backup.daily`

- local proof of backup behavior

### Wave 5 — policy workflow shell

Done.  
This is the first fully real Admin-native workflow:

- index

- detail

- preview/diff

- validation display

- commit flow

- tested Governance seam

- tested Admin service/route shell

## Partially done / needs hardening

### Wave 4 — cron supervision

This is functionally present, but not finished.

What is still left here:

- external backup copy + verification on the production machine

- forced failure proof for second-failure escalation

- Admin inbox visibility for cron failures in a live path

- probably a small aggregation polish pass on the cron page

- maybe config cleanup for backup roots / external target handling

### Wave 6 — auth operator surface

This is the biggest “not really done yet” item if we are being strict.

You have Auth slice hardening work and posture, but not yet a clearly finished **Admin-facing operator surface** for:

- operator list/search

- lock/unlock

- reset flows

- inactive user archive request/approval handoff

- role/status supervision

- safe maintenance actions

So I would mark Wave 6 as **started conceptually, not completed**.

## Still clearly ahead of us

### Wave 7 — reports

Still ahead.

Likely includes:

- Admin/ops reports

- cron/maintenance reports

- archive status reports

- policy drift / validation visibility if you want it

- later cross-slice audit/admin reporting

### Wave 8 — additional slice integrations

Still ahead.

This probably means Admin control-surface integrations for:

- Governance policy management beyond current shell

- Auth maintenance

- maybe Ledger/Finance archival controls

- maybe Logistics diagnostics

- maybe unified admin review overlays where truly justified

## The hidden backlog under the new cron/archive work

Separate from those waves, you also created a new mini-roadmap:

### Records lifecycle / archive backlog

Still left:

- land `records_lifecycle` policy cleanly

- land its schema cleanly

- add package policy cleanly

- likely add archive manifest schema

- design archive request/approval path for inactive Resource/Sponsor/User

- build archive jobs:
  
  - `archive.ledger.yearly`
  
  - `archive.finance.yearly`
  
  - later on-demand inactive entity archive jobs

- define hot-store stub/index behavior for archived-offline batches

That is real work, and it sits mostly under Wave 4 plus Wave 8.

## My honest status summary

If I collapse it down:

### Broadly complete

- Waves 0 through 5

### In progress / partially complete

- Wave 4 hardening

- Wave 6

### Not really started yet

- Wave 7

- Wave 8

## What I would do next

The best next move is **not** to jump to reports yet.

I would do this order:

1. finish `backup.daily` hardening

2. land `records_lifecycle` policy/schema/package-policy cleanly

3. build archive request/approval semantics for inactive User/Resource/Sponsor

4. then build the first archive job

5. then circle back to Wave 6 Auth operator surface

Why that order:

- it keeps momentum with the cron/archive work you just opened

- it turns policy into executable operations

- it avoids drifting into report/UI work before the underlying maintenance workflows exist

So the short answer to “what do we have left?” is:

**Auth operator surface, cron hardening, archive lifecycle execution, reports, and the broader slice-integration layer.**

And the most immediate real work is:  
**finish backup.daily, then move from archive policy to archive workflow.**

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

---

Good call. Here’s a foundation-pass checklist you can work straight from.

# Admin rebuild — Wave 0 and Wave 1 checklist

## Wave 0 — clean scaffold

### Objective

Stand up a fresh Admin slice that is alive, readable, and on-mission  
before any real feature weight gets added.

### Exit gate

Wave 0 is done when:

- Admin blueprint registers cleanly

- all starter pages render

- page purpose is clearly observe / triage / supervise / launch

- no service commits

- no foreign write behavior exists

- no “misc maintenance” escape hatch exists

---

## Wave 0A — pin the foundation rules

### Checklist

- Pin the Admin charter in project canon docs

- Pin the Code Rule you just finalized

- Pin the “no orphaned review flags” rule

- Pin a short Admin anti-pattern list:
  
  - no universal fixer
  
  - no direct cross-slice bypass
  
  - no devtools spillover
  
  - no foreign semantics in Admin
  
  - no misc maintenance bucket

- Pin the first-wave scope:
  
  - dashboard
  
  - inbox shell
  
  - cron supervision
  
  - policy workflow shell
  
  - auth operator surface

### Deliverable

One short canon entry that defines what Admin is and is not.

---

## Wave 0B — create the clean slice shell

### Suggested file scaffold

```text
app/slices/admin/
    __init__.py
    routes.py
    services.py
    mapper.py
    forms.py                  # only if truly needed now
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
tests/slices/admin/
    test_admin_routes.py
    test_admin_dashboard.py
    test_admin_inbox.py
```

### Checklist

- Create fresh `app/slices/admin/`

- Create `__init__.py` with Admin blueprint only

- Add `routes.py`

- Add `services.py`

- Add `mapper.py`

- Add template folders

- Register blueprint in app startup

- Do not carry over old Admin code by default

### Guardrails

- No cross-slice imports except through proper contracts/extensions

- No direct SQL in templates or route glue

- No placeholder repair routes

- No persistence layer yet unless truly required

---

## Wave 0C — wire minimal starter routes

### Starter routes

- `GET /admin/` → dashboard

- `GET /admin/inbox/`

- `GET /admin/cron/`

- `GET /admin/policy/`

- `GET /admin/auth/operators/`

### Checklist

- Each route renders a page

- Each page has a single clear purpose

- Each page uses Admin layout/templates only

- No route performs foreign writes

- No route performs corrective work

- No placeholder links to nonexistent features

### Deliverable

A live but intentionally thin Admin slice.

---

## Wave 0D — create minimal page shells

### Dashboard shell should contain

- page title

- one-line mission statement

- placeholder regions for:
  
  - inbox summary
  
  - cron health
  
  - policy health
  
  - auth summary
  
  - slice health cards

### Inbox shell should contain

- table/list placeholder

- filters placeholder

- item status legend

### Cron shell should contain

- jobs summary placeholder

- recent runs placeholder

- failure/stale placeholder

### Policy shell should contain

- policy list placeholder

- validation summary placeholder

### Auth operators shell should contain

- operators list placeholder

- status summary placeholder

### Guardrail

- No shell should contain repair verbs like “fix database”

- No shell should imply Admin owns foreign semantics

---

## Wave 0E — establish route/service posture

### Checklist

- Routes stay thin

- Services only compose/read

- Services do not commit

- Services do not own foreign business rules

- Mapper holds Admin view shaping only

- Any future write path must call owning-slice interface

### Suggested internal rule

- If a function sounds like “repair,” “reconcile,” “unlock,”  
  “validate-policy,” or “save-policy,” it probably belongs elsewhere

---

## Wave 0F — smoke tests

### Minimum test set

- Admin blueprint registers

- dashboard route returns 200

- inbox route returns 200

- cron route returns 200

- policy index route returns 200

- auth operators route returns 200

### Architecture tests

- no service commits transactions

- no route links to missing endpoints

- no “misc maintenance” page exists

- no old repair/devtools routes leaked in

### Deliverable

A green, minimal slice with no architectural cheating.

---

# Wave 1 — read-side backbone

## Objective

Define the internal Admin vocabulary before page sprawl starts.

## Exit gate

Wave 1 is done when:

- core Admin DTOs exist

- dashboard/inbox/cron/policy/auth pages can all be expressed in those DTOs

- Admin is composing read models, not inventing domain meaning

- at least one dashboard page renders from real DTOs, even if data is stubbed

---

## Wave 1A — define DTO/view shapes

### Create first-pass read DTOs

- `DashboardDTO`

- `SliceHealthCardDTO`

- `InboxSummaryDTO`

- `InboxItemDTO`

- `CronJobStatusDTO`

- `PolicyHealthSummaryDTO`

- `AuthOperatorSummaryDTO`

### DTO design rule

- operator-facing only

- no foreign truth ownership

- no embedded write semantics

- no giant catch-all payload DTO

### Suggested fields

#### `SliceHealthCardDTO`

- `slice_key`

- `label`

- `status`

- `summary`

- `attention_count`

- `launch_route`

#### `InboxSummaryDTO`

- `total_open`

- `high_severity`

- `stale_count`

- `by_slice`

- `by_issue_kind`

#### `InboxItemDTO`

- `source_slice`

- `issue_kind`

- `severity`

- `summary`

- `opened_at_utc`

- `status`

- `resolution_route`

- `allowed_actions_summary`

- `context_preview`

#### `CronJobStatusDTO`

- `job_key`

- `label`

- `last_success_utc`

- `last_failure_utc`

- `status`

- `stale`

- `note`

#### `PolicyHealthSummaryDTO`

- `policy_count`

- `valid_count`

- `warning_count`

- `error_count`

- `last_checked_utc`

#### `AuthOperatorSummaryDTO`

- `active_operator_count`

- `disabled_operator_count`

- `locked_operator_count`

- `attention_count`

#### `DashboardDTO`

- `inbox_summary`

- `cron_summary`

- `policy_summary`

- `auth_summary`

- `slice_cards`

- `recent_activity_summary`

---

## Wave 1B — map responsibility for each DTO

For each DTO, answer two things:

1. Who owns the truth?

2. Is Admin composing or merely relaying?

### Checklist

- Document source for each DTO

- Mark which fields are Admin-local

- Mark which fields must come from owning slice projections

- Mark which DTOs may start stubbed

- Refuse any field that drags foreign write semantics into Admin

### Example posture

- `PolicyHealthSummaryDTO`
  
  - Governance owns meaning
  
  - Admin displays summary

- `AuthOperatorSummaryDTO`
  
  - Auth owns truth
  
  - Admin displays summary

- `InboxItemDTO`
  
  - source slice owns issue meaning
  
  - Admin owns queue presentation/status metadata

---

## Wave 1C — create mapper functions

### Checklist

- Add small, single-purpose mapper functions in `mapper.py`

- Keep mapper functions pure

- Map raw read payloads into Admin DTOs

- Do not hide business logic in mapper functions

- Keep naming obvious and slice-local

### Examples

- `to_slice_health_card(...)`

- `to_inbox_item(...)`

- `to_cron_job_status(...)`

- `to_policy_health_summary(...)`

- `to_auth_operator_summary(...)`

- `to_dashboard(...)`

---

## Wave 1D — create read composition services

### Checklist

- Add `get_dashboard()`

- Add `list_inbox_items()`

- Add `get_inbox_summary()`

- Add `list_cron_jobs()`

- Add `get_policy_health_summary()`

- Add `get_auth_operator_summary()`

### Guardrails

- Services are read-only

- Services do not commit

- Services do not persist foreign truth

- Services do not redefine slice semantics

- If real projections are not ready yet, return clearly stubbed DTOs

---

## Wave 1E — stub the first data sources safely

For the foundation pass, it is fine to start with controlled stubs.

### Checklist

- Decide which summaries are stubbed in Wave 1

- Label stubbed values clearly in code comments

- Avoid fake complexity

- Do not reach into foreign tables just to avoid a stub

- Prefer a clean stub over an architectural shortcut

### Good early stub candidates

- slice health cards

- inbox summary

- recent critical activity summary

### Better early real candidates

- cron summary, if Admin owns it

- policy health summary, if Governance already exposes a safe read path

- auth operator summary, if Auth already has a safe read surface

---

## Wave 1F — wire DTOs into pages

### Checklist

- dashboard route returns `DashboardDTO`

- inbox route returns `InboxSummaryDTO` + list of `InboxItemDTO`

- cron route returns list of `CronJobStatusDTO`

- policy index returns `PolicyHealthSummaryDTO`

- auth operators page returns `AuthOperatorSummaryDTO`

### Deliverable

Pages now render from a defined Admin read model instead of freehand logic.

---

## Wave 1G — test the read backbone

### DTO tests

- mapper returns expected DTO shapes

- DTO defaults are sane

- no DTO contains foreign write-state fields

### Service tests

- `get_dashboard()` returns `DashboardDTO`

- `list_inbox_items()` returns `InboxItemDTO` list

- `list_cron_jobs()` returns `CronJobStatusDTO` list

- service layer remains read-only

### Route tests

- routes render DTO-backed pages

- no missing template variables

- no broken links to not-yet-built routes

### Architecture tests

- no commit calls in Admin services

- no hidden foreign write behavior

- no catch-all “maintenance tools” registry appears

---

# Recommended stop point after Wave 1

Do not rush into policy commit flows or Auth actions yet.

After Wave 1, stop and verify:

- Admin reads cleanly as a control surface

- DTO vocabulary feels sufficient

- no accidental semantics leaked into Admin

- templates are simple and on-mission

- next step should naturally be Dashboard polish, then Inbox shell

If that all feels good, move into:

- Wave 2 Dashboard

- Wave 3 Inbox shell

---

# Suggested first sprint cut

If you want the smallest practical slice of work first:

## Sprint A

- create fresh slice scaffold

- add route shells

- add templates

- register blueprint

- add smoke tests

## Sprint B

- add DTO classes

- add mapper functions

- add stubbed read services

- wire dashboard and inbox to DTOs

- add DTO/service tests

That gives you a clean foundation without overcommitting.

If you want, I’ll turn this into a copy-pasteable markdown checklist block for your local canon or TODO file.
