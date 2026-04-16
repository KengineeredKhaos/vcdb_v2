# VCDB v2 Dev Runbook

## Purpose

This runbook exists to keep a future developer from stepping on known
landmines.

It is the operational companion to the project canon. It records the
practices, maintenance procedures, dependency chains, and diagnostic habits
that protect the application from silent breakage.

This document is for:

- preserving critical maintenance knowledge
- standardizing repeatable development procedures
- documenting cross-slice bear traps and trip wires
- showing where "small" edits can ripple across the system
- helping a successor understand not just what the rules are, but why they
  exist

## What This Document Is and Is Not

This runbook **is**:

- a future-developer survival manual
- a place for practical procedures and recovery steps
- a place to record fragile seams before they are forgotten
- a staging ground for rules that may later become canon

This runbook is **not**:

- the Ethos document
- the formal policy source of truth
- the Governance policy store
- a dumping ground for random snippets with no operational value

If a note prevents silent breakage, it belongs here.
If a note becomes stable project law, promote it into canon.

---

## Audience

Primary audience: the next maintainer of VCDB v2.

Assume that Future Dev:

- did not live through the refactors
- does not know which seams are historically fragile
- may misread an old helper or stale route as live architecture
- needs explicit warnings where a "simple cleanup" can corrupt system truth

Write for that person.

---

## Reading Order for Future Dev

Read these sections in order:

1. Operating invariants
2. Change-control playbooks
3. Diagnostics and recovery procedures
4. Admin repair doctrine
5. Parking lot / scratchpad

That order explains:

- what must never drift
- how to make changes safely
- how to diagnose breakage when drift still happens

---

## Document Rules

- Keep entries practical.
- Prefer explicit checklists over narrative.
- Capture the trip wire as soon as it is discovered.
- Do not wait for polish before documenting a hazard.
- Name the ownership boundary whenever the issue crosses slices.
- Record validation steps for every non-trivial procedure.
- If a rule becomes project law, move it into canon and leave only the
  operational summary here.

---

## Entry Template

### Title

**Why this matters**

**Trip wire**

**What can break**

**Ownership boundary**

**Required procedure**

**Validation / checks**

**Canonical references**

**Notes / follow-up**

---

## 1. Operating Invariants

These are the non-negotiable patterns most likely to become bear traps when
ignored.

### 1.1 Nothing happens in the dark

- Every meaningful mutation must leave an explainable trail.
- Ledger is part of the truth story, not decorative logging.
- No silent repairs.
- No "helpful" history rewriting.

### 1.2 Nothing is deleted; records are archived by policy

- Do not normalize destructive edits into ordinary maintenance.
- Historical truth must remain explainable.
- If something must leave hot storage, it does so through a retention or
  archive procedure, not casual deletion.

### 1.3 Skinny routes, fat services

- Routes parse, authorize, respond, and commit.
- Services perform domain work.
- Services do not become hidden controllers.
- Routes do not become business-logic kitchens.

### 1.4 Slices own their own truth

- A slice owns its models, services, and data access.
- Cross-slice interaction goes through versioned Extensions contracts.
- Do not reach across slice boundaries for convenience.
- Admin is a control surface, not an owner of foreign slice truth.

### 1.5 Ledger carries references, not PII

- No PII in Ledger.
- No PII in cross-slice audit logs.
- Use ULIDs and safe references.

### 1.6 Mutations follow one transaction story

The standing rule:

1. write domain rows
2. `db.session.flush()`
3. emit Ledger/event-bus entry
4. return result/DTO
5. commit at the outer route or workflow boundary

This rule is repeated later in Finance because it is especially dangerous
there, but it is broader than Finance.

### 1.7 `request_id` is workflow glue

- `request_id` is not decorative.
- It is the correlation seam across Ledger, Finance, Calendar, Sponsors,
  diagnostics, and repair playbooks.
- Do not replace it with a row ULID.
- Do not generate new ones mid-flow unless you are starting a genuinely new
  workflow.

### 1.8 Governance policy files are source-controlled truth

- Governance policy lives in JSON under the Governance data store.
- Admin edits policy through controlled workflows.
- Slices consume policy meaning; they do not invent their own policy shadows.

---

## 2. Change-Control Playbooks

These entries describe maintenance tasks that look small but can break several
slices if performed casually.

### 2.1 Adding a new finance semantic key

**Why this matters**

Governance owns the finance vocabulary, but Finance owns how that vocabulary
lands on the Chart of Accounts.
A semantic key can be valid policy while still being unusable in actual
posting.

**Trip wire**

A developer adds or changes a semantic key such as `expense_kind` in
Governance taxonomy and assumes the system now knows what to do with it.
It does not.

**What can break**

- Calendar may begin hinting a new semantic key.
- Governance validation may pass.
- Finance posting may fail because `posting_map_v1.json` has no route for the
  new key.
- Automated COA selection may drift or fail silently unless validation catches
  the gap.

**Ownership boundary**

- Governance owns the words.
- Calendar may hint the words.
- Finance owns where the words land.
- Posting services interpret; they do not invent vocabulary.

**Required procedure**

When adding, renaming, deprecating, or repurposing a finance semantic key:

1. Update `policy_finance_taxonomy.json`.
2. Validate the policy file against its schema.
3. Decide whether the key is postable now or reserved for future use.
4. If the key is postable, update `finance/data/posting_map_v1.json`.
5. Confirm `finance/services_semantics_posting.py` accepts and routes the key
   correctly.
6. Update any relevant `calendar/taxonomy.py` `finance_hints` entries.
7. Run policy validation and drift tests.
8. Run Finance semantic-posting tests.
9. Record any non-obvious consequence in this runbook.

**Validation / checks**

Minimum checks:

- every Calendar `finance_hints.expense_kinds[]` key exists in Governance
  taxonomy
- every Finance posting-map key exists in Governance taxonomy
- every Governance postable `expense_kind` exists in `posting_map_v1.json`
- `policy-health` passes cleanly
- Finance posting tests pass cleanly

**Canonical references**

- `slices/governance/data/policy_finance_taxonomy.json`
- `slices/finance/data/posting_map_v1.json`
- `slices/finance/services_semantics_posting.py`
- `slices/calendar/taxonomy.py`

**Notes / follow-up**

This should remain a pinned maintenance checklist.

---

### 2.2 Governance policy metadata block consistency

**Why this matters**

Governance policy inventory, schema validation, diagnostics, and future admin
editing depend on policy files sharing one predictable metadata shape.

**Trip wire**

Policies evolve with inconsistent `meta` blocks and the tooling gradually stops
being able to reason about them uniformly.

**What can break**

- schema validation becomes uneven
- policy inventory becomes harder to trust
- admin tooling becomes more brittle
- future diff/preview workflows become inconsistent

**Ownership boundary**

Governance owns policy structure. Admin may edit through controlled workflows,
but does not redefine metadata shape.

**Required procedure**

Each Governance policy JSON should carry the same required `meta` structure:

- `description`
- `effective_on`
- `notes`
- `policy_key`
- `schema_version`
- `status`
- `title`
- `version`

**Validation / checks**

- schema validation requires the full `meta` block
- policy-health fails on malformed or incomplete metadata

**Canonical references**

- Governance policy JSON files
- Governance policy schemas
- policy-health diagnostics

**Notes / follow-up**

Keep this entry short here; the full metadata contract belongs in Governance
canon and schema definitions.

---

### 2.3 Adding a new Resource capability key

**Why this matters**

A Resource capability is not complete when it exists only in taxonomy.
Capability vocabulary and customer-need matching are a paired maintenance task.

**Trip wire**

A developer adds a new capability to `resources/taxonomy.py` but never makes an
explicit decision about whether and how it participates in Customer-to-Resource
matching.

**What can break**

- drift between provider vocabulary and matching behavior
- false assumption that providers with the new capability are matchable
- future confusion about whether the omission was intentional or accidental

**Ownership boundary**

- `resources/taxonomy.py` defines what a provider can do
- `resources/matching_matrix.py` defines whether the capability participates
  in matching

**Required procedure**

When adding a new Resource capability key:

1. add the capability to `resources/taxonomy.py`
2. make an explicit matching decision in `resources/matching_matrix.py`
3. if the capability should not participate in matching, document that choice
4. rerun Resource matching tests
5. record any unusual rule here if the decision is surprising

**Validation / checks**

- matching tests pass
- no new taxonomy key exists without an explicit matching decision

**Canonical references**

- `resources/taxonomy.py`
- `resources/matching_matrix.py`
- Resources contract tests

**Notes / follow-up**

A capability added without a matching decision is incomplete work.

---

### 2.4 Sponsors fulfillment must preserve one workflow `request_id`

**Why this matters**

Sponsor realization is part of the same cross-slice money story as Calendar
publication and Finance posting. If Sponsors invents, drops, or duplicates the
workflow identifiers, the audit trail fractures.

**Trip wire**

A developer patches sponsor fulfillment and accidentally:

- duplicates a keyword like `request_id=` in a call site
- invents a new request ID mid-flow
- replaces the workflow timestamp with a fresh "now"
- treats request correlation as optional

**What can break**

- import-time `SyntaxError` on duplicated keyword arguments
- broken Calendar or Sponsors tests
- fragmented Ledger trail across multiple request IDs
- fulfillment events that no longer line up with Finance postings

**Ownership boundary**

Sponsors owns fulfillment workflow behavior. Finance owns posting facts.
Ledger records the story both must agree on.

**Required procedure**

For sponsor funding realization flows:

1. accept the caller's `request_id` and `happened_at_utc`
2. pass them through unchanged into the Finance seam
3. emit Ledger with the same `request_id`
4. do not generate a fresh timestamp if the workflow already has an
   authoritative event time
5. after signature cleanup, rerun sponsor, calendar, and contract tests

**Validation / checks**

- `tests/slices/sponsors/`
- `tests/slices/calendar/`
- `tests/extensions/contracts/`

**Canonical references**

- Sponsors fulfillment services
- Calendar funding workflow seams
- Finance posting seams

**Notes / follow-up**

This is a classic example of a small edit with broad blast radius.

---

### 2.5 Canonical write-path discipline (`flush -> emit -> route commit`)

The premise is services flush relevant session domain data first, then stage Ledger data (event_bus.emit) on the db.session. Routes verify operation completeness & commit domain data and Ledger entry data. **Services flush and stage event_bus.emit on the db session -> Routes Commit. One shared request_id throughout the transaction**

**Why this matters**

If Domain writes and Ledger writes do not follow one disciplined transaction story, the application can create ghost trail entries or partial money workflows that are hard to explain and even harder to repair. Particularly where Finance and Ledger are concerned, those slices are foundational to the audit process and largely opaque to Staff operators. If write-path discipline degrades, transaction correlation is compromised, the primary purpose of the application is effectively defeated and admin operator repair work quickly becomes ledger spam.

**Trip wire**

A developer commits inside a Domain service, emits Ledger before flush, or
starts treating `request_id` as optional.

**What can break**

- Ledger trail survives while domain truth rolls back
- Domain table rows commit before the larger workflow is finished
- cross-slice flows become harder to trace
- services begin inventing fake request IDs

**Ownership boundary**

Domains owns domain facts. Routes own final commit. Ledger owns the audit story.

**Required procedure**

For Domain mutating flows:

1. validate inputs and policy assumptions
2. write domain rows
3. `db.session.flush()`
4. emit Ledger via `event_bus.emit(...)`
5. return DTO/result
6. commit only at the outer route or workflow boundary

Rules:

- services do not commit
- Ledger emit happens after flush
- routes commit once
- never use a row ULID as fake `request_id`
- use canonical request context or explicit caller-provided `request_id`

**Validation / checks**

In a case where Calendar funding demand flows change: 

- Finance tests still pass
- Calendar and Sponsors cross-slice tests still pass
- Ledger entries and domain rows share the same `request_id`
- rollback removes both domain writes and the corresponding Ledger emit when
  the workflow fails before commit

**Canonical references**

- `app/lib/request_ctx.py`
- `app/extensions/event_bus.py`
- Domain service write paths

**Notes / follow-up**

This is one of the most important habits in the application.

---

### 2.6 Refactor cadence for seam cleanup

**Why this matters**

Large seam cleanups can create misleading red test output when too many moving
parts change between reruns.

**Trip wire**

A developer tries to clean contracts, bridges, services, tests, and templates
all at once and then has no idea which failure is real.

**What can break**

- syntax mistakes hide real architectural outcomes
- auth changes get mixed into seam cleanup
- stale monkeypatches create noisy failures
- the patch quality becomes harder to judge

**Ownership boundary**

This is a process rule spanning all slices.

**Required procedure**

Use this cadence:

1. clean one seam
2. rerun only the directly affected tests
3. fix immediate fallout
4. move to the next seam
5. rerun broader slice suites only after the local seam is green

Do not treat broad red test output as one problem until narrow seam tests have
been rerun.

**Validation / checks**

After each seam:

- rerun affected slice tests
- rerun affected contract tests
- then rerun wider suites

**Canonical references**

- contract DTO seams
- bridge/service seams
- auth route seams

**Notes / follow-up**

Especially important during DTO moves, `request_id` cleanup, and cross-slice
bridge refits.

---

## 3. Diagnostics and Recovery Procedures

These entries are for finding drift, not just warning that drift exists.

### 3.1 Route access sweep (`tools/route_access_sweep.py`)

**Why this matters**

Manual clicking creates false confidence. The route sweep is a broad
operator-surface smoke check that helps separate expected denials from stale
surfaces and real failures.

**Trip wire**

A developer changes auth flow, route guards, public landing behavior, or slice
routes and assumes the app is still healthy because a few pages looked fine by
hand.

**What can break**

- public routes silently redirect to login
- logged-in routes bounce to change-password or logout
- staff/auditor/admin access boundaries drift
- stale registered routes survive unnoticed
- a route still exists but its service or template no longer does
- a GET route starts returning `400` because it wrongly expects query state on
  first load

**Ownership boundary**

This is a diagnostics tool. It does not replace slice tests.

**Required procedure**

Before running the sweep:

1. run from repo root
2. use real login mode in development, not stub auth
3. confirm seeded operators exist in the current dev DB
4. if operators are fresh, log in manually once as each user and complete the
   forced password change
5. update the sweep script with the current dev passwords if needed
6. confirm development is running in production-like auth posture:
   - no auto-login
   - no header-auth scaffold
   - no dev stub auth

Run:

```bash
python tools/route_access_sweep.py --env dev
```

**Validation / checks**

Interpretation:

- `OK` = expected 2xx response
- `REDIRECT` = expected 3xx redirect
- `DENIED` = expected access denial such as 401/403
- `BAD` = real problem, including abnormal 4xx, 5xx, or probe-caught
  exceptions

Read results using these rules:

1. many redirects to `/auth/change-password` means auth normalization is not
   complete yet
2. the same failure across all roles suggests stale implementation or shared
   helper drift, not role gating
3. expected denials on admin-only routes are healthy
4. a GET route returning `400` for all roles suggests bad request parsing on
   initial load
5. status `0` with an exception name usually means the route threw before a
   normal HTTP response existed

Healthy signs:

- admin reaches most operator/admin surfaces
- denial patterns are consistent
- only a small explainable set of routes is flagged
- public landing remains public
- login/logout behavior is stable

**Canonical references**

- `tools/route_access_sweep.py`
- Auth slice
- route registry diagnostics

**Notes / follow-up**

- keep sweep output as disposable diagnostics, not canon data
- review both CSV and JSON output
- delete stale routes when appropriate instead of sentimental repair
- rerun after major auth, routing, or slice-surface refactors

---

### 3.2 Migration and stale test DB trap

**Why this matters**

Local development, tests, and production startup do not share identical runtime
posture. It is easy to upgrade one DB and mistakenly believe all environments
match.

**Trip wire**

A developer runs migration work through the wrong entrypoint, upgrades `dev.db`,
and forgets that pytest is still using stale `test.db`.

**What can break**

- production config validation fires during local migration work
- migrations appear broken when the real issue is wrong startup path
- new tables exist in `dev.db` but not in `test.db`
- tests fail with "no such table" after a valid migration

**Ownership boundary**

This is an environment and tooling discipline issue, not a slice-local defect.

**Required procedure**

For local migration and upgrade work:

1. run CLI commands through `manage_vcdb.py`
2. set `VCDB_ENV` explicitly
3. remember that test runs default to `app/instance/test.db`
4. after schema changes, upgrade the testing DB too
5. if necessary, remove stale `test.db` and recreate it cleanly

Example:

```bash
VCDB_ENV=development flask --app manage_vcdb.py db migrate -m "..."
VCDB_ENV=development flask --app manage_vcdb.py db upgrade
VCDB_ENV=testing flask --app manage_vcdb.py db upgrade
```

**Validation / checks**

- confirm which DB file the current environment is using
- confirm migrations were applied to both dev and test DBs when appropriate
- rerun the slice tests touching the new schema

**Canonical references**

- `config.py`
- `manage_vcdb.py`

**Notes / follow-up**

When a migration appears broken, check the DB target before blaming Alembic.

---

### 3.3 Shared template macro contract drift

**Why this matters**

Shared Jinja macros are part of the app's UI contract. If a macro expects one
object shape and the shared helper provides another, the defect can surface all
over the app.

**Trip wire**

A shared macro is written against one interface while the helper object exposes
similar but different names.

Example:

- template pagination macro expects `has_prev`, `has_next`, `prev_num`, `next_num`
- shared pagination helper provides `prev_page`, `next_page`

**What can break**

- route-access sweeps report routes as broken even when auth is fine
- slice templates fail because shared UI plumbing drifted
- developers patch individual templates instead of the shared seam
- the same defect appears in multiple slices at once

**Ownership boundary**

Shared template macros and shared helper objects form one compatibility seam.
Repair the seam, not every downstream consumer.

**Required procedure**

When a shared macro fails on an expected attribute:

1. inspect the macro contract first
2. inspect the shared object/helper second
3. repair the mismatch at the shared seam if the macro contract is already
   established across slices
4. avoid per-template workaround logic unless the variation truly belongs to
   the template
5. add or update a direct compatibility test at the library level

**Validation / checks**

- rerun directly affected slice tests
- rerun any route-access smoke that first exposed the issue
- add a library/unit test proving the helper exposes the macro-required
  attributes

**Canonical references**

- shared Jinja macros
- `app/lib/pagination.py`
- affected slice templates

**Notes / follow-up**

Heuristic: if the same helper/template failure appears across roles or slices,
suspect shared contract drift before suspecting route security.

---

## 4. Admin Repair Doctrine

### 4.1 Finance repair doctrine (short form)

**Why this matters**

Admin is the repair technician. Auditor is read-only. Finance repair tooling
must never become a hidden backdoor into accounting truth.

**Trip wire**

A future developer starts building "helpful" admin repair tools that:

- edit `Journal` or `JournalLine` in place
- delete Ledger rows
- rewrite history so a bad posting appears never to have happened
- bypass slice services and mutate tables directly

**What can break**

- accounting trail loses credibility
- Ledger no longer tells the true story
- Admin becomes a hidden superuser instead of a controlled repair surface
- Future Dev cannot explain what actually happened

**Ownership boundary**

Admin owns controlled repair workflows. It does not own accounting truth and it
does not get to revise history out of embarrassment.

**Required procedure**

Finance/Admin repairs must follow these rules:

- Auditor is read-only
- Admin performs only explicit corrective playbooks
- no in-place journal amount edits
- no Ledger row deletion
- no history rewriting
- use reversal, repost, rebuild, or workflow-resolution patterns instead
- require reason, preview, fresh repair `request_id`, flush, emit, and outer
  route commit

**Validation / checks**

- every repair leaves an explainable Ledger trail
- the original mistake remains historically visible
- an Auditor can explain the repair without guessing

**Canonical references**

- Admin slice repair surfaces
- Finance Admin Toolkit Blueprint
- Ledger doctrine

**Notes / follow-up**

Keep only the short form here. The full toolkit design belongs elsewhere.

---

## 5. Parking Lot

These are known follow-up topics that deserve fuller writeups.

- Funding Plan revision behavior versus Finance factual history
- sponsor return-unused vs operations repayment vs project loss write-off
- source-profile chain from Calendar Funding Plan to Governance preview to
  Finance posting
- drift tests between Governance taxonomy, Calendar finance hints, Finance
  posting map, and posting services
- any future end-to-end checklist that proves semantic-key changes are fully
  postable

---

## 6. Scratchpad / Snippet Intake

Use this section only for newly discovered hazards that have not yet been filed
into the correct section.

Rule:
A scratchpad note must either be promoted into a real runbook entry or deleted
once it proves non-actionable.

- *Empty for now.*

---

## Maintenance Reminder

This runbook becomes valuable only if it stays curated.

When adding a note, always decide:

1. Is this an invariant?
2. Is this a change-control playbook?
3. Is this a diagnostic or recovery procedure?
4. Is this an Admin repair doctrine item?
5. Is this only parking-lot material?

If the answer is none of those, the note probably belongs somewhere else.

**New Entry Format**

- why it matters
- what the trip wire is
- what can break
- who owns the boundary
- required procedure
- validation
- canonical references
