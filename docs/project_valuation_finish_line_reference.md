# Project Valuation and Finish-Line Planning

## Purpose

This document condenses the main conclusions from the discussion into a single practical reference for hardcopy use. It is intended as an internal planning aid for:

- rough statement-of-work framing
- fair-market valuation of the in-kind software contribution
- realistic remaining timeline expectations
- launch-fence discipline to prevent scope creep and rabbit-holeing

---

## 1. Rough Development Timeline Since September 2025

### September 2025 — Architecture and Canon Lock-In

This period appears to have been primarily focused on system design, architectural discipline, and domain modeling.

Main accomplishments:

- vertical-slice structure established as the governing pattern
- skinny routes / fat services adopted as a core principle
- strong cross-slice boundary rules established
- v2 blueprint and layout conventions defined
- audit and ledger expectations sharpened
- Governance, Resources, Sponsors, Customer, and Ledger responsibilities clarified
- officer/governance authorization model developed
- sponsor restrictions, overrides, and resource classification concepts refined
- reimbursement, pass-through, and allocation lifecycle thinking advanced

Summary judgment:
This was largely architecture and business-rules work rather than surface polish.

### October 2025 — Contract Model and System Backbone

This period appears to have solidified the contract-driven shape of the system.

Main accomplishments:

- Extensions/contracts established as the official cross-slice seam
- ULID locked in as the canonical ID strategy
- Admin reframed as a control/triage surface rather than a bypass slice
- Transactions renamed to Ledger for clarity
- Governance policy storage pushed toward JSON under governance data
- README/canon/charter concepts solidified

Summary judgment:
This was foundational system hardening and conceptual cleanup.

### November 2025 — Validation and Durability Thinking

Focus shifted toward making the architecture durable and supportable.

Main accomplishments:

- governance policy schema/validation pipeline elevated as a real requirement
- guided admin policy editing identified as a future need
- startup, migration, seeding, and test-discipline thinking formalized
- devtools explicitly treated as temporary/disposable

Summary judgment:
This phase emphasized survivability and maintainability.

### January–February 2026 — Invariants and Canon Details

This period appears to have stabilized lower-level invariants and implementation rules.

Main accomplishments:

- canonical enum/value sets established for forms and workflows
- facet-table invariants for Sponsor and Resource keyed by entity ULID
- slice-local mapper rule standardized
- formatting and consistency rules pinned down
- PII placement decisions clarified

Summary judgment:
This was stabilization work so implementation could proceed on firm rules.

### March 2026 — Cleanup, Drift Reduction, and Operational TODO Capture

Focus appears to have shifted toward cleanup and trimming old transitional seams.

Main accomplishments:

- compatibility shims identified for removal
- finance bridge signatures cleaned up
- ProjectPolicyHints contract cleanup pursued
- legacy funding_decisions scraps identified for removal
- targeted rerun discipline preferred over broad blind retesting
- operational TODOs captured for CSRF audit, logistics reconciliation, admin inbox consolidation, name-card standardization, and finance/calendar taxonomy drift

Summary judgment:
This was cleanup and operationalization work.

### April 2026 — MVP Hardening and Proof-by-Tests

This is the clearest period of visible implementation maturity.

Main accomplishments:

- Customer / Resource / Logistics workflows materially proven
- referral creation from customer follow-up flow repaired
- CustomerHistory writes and Logistics issuance behavior demonstrated
- Finance MVP hardening completed with full test suite green
- Calendar draft/promotion/funding flows repaired and green
- route access/security sweeps performed and stale surfaces identified
- pagination and DTO cleanup performed
- test harness weaknesses exposed, especially seeding overhead
- operator onboarding reviewed
- beta deployment preparation began
- Dev Runbook reorganization and future-maintainer guidance advanced

Summary judgment:
This phase marks the shift from scaffolding into a credible beta-stage application.

---

## 2. Overall Development Arc

The work since September 2025 falls into three broad phases:

1. **Canon and architecture formation**
   
   - fall 2025

2. **Contract and invariant stabilization**
   
   - winter 2025–2026

3. **MVP hardening and operator-surface proofing**
   
   - spring 2026, especially April

Plain-language summary:
A substantial amount of real development work has been accomplished. The record does not read like casual experimentation. It reads like a steady progression from architecture freeze, to boundary and policy refinement, to testable subsystem hardening, to beta deployment preparation.

---

## 3. Estimated Billable Manhours to Reach the Present State

### Rough Estimate

Estimated effort for a real-world software team to reach the current state:

- **Low end:** 1,100 hours
- **Most likely planning number:** 1,400 hours
- **Upper end:** 1,800 hours

This estimate reflects the work required to get to the current project state, not a fully polished final product.

### What That Effort Includes

The estimate assumes completion of work comparable to the following:

- architecture and canon establishment
- slice boundaries and contracts defined
- multiple slices materially implemented and hardened
- major testing and refactor cycles completed
- core operator workflows proven
- route/access sweeps underway
- deployment planning underway
- documentation and system-shape thinking substantially written down

### Rough Labor Breakdown

#### 1. Discovery, domain modeling, architecture decisions

- **180–300 hours**

#### 2. Core application scaffolding and cross-slice framework setup

- **120–220 hours**

#### 3. Slice implementation and hardening

- **450–750 hours**

#### 4. Tests, regressions, refactors, cleanup passes

- **180–320 hours**

#### 5. Documentation, runbooks, deployment prep, operator thinking

- **90–180 hours**

### Practical Planning Numbers

For practical comparison:

- **Lean / efficient / senior-heavy team:** 1,100–1,300 hours
- **Normal competent shop:** 1,300–1,700 hours
- **Heavier process / more meetings / more handoff overhead:** 1,700–2,200 hours

### Working Summary

If a single-number estimate is needed:

> **Use 1,400 billable hours as the anchor estimate.**

If a safer budgetary envelope is needed:

> **Use 1,250 to 1,750 hours.**

---

## 4. Fair-Market In-Kind Value Estimate

### Practical Valuation Goal

This valuation is intended for internal partnership/sponsorship tier thinking and fair-market replacement value, not tax appraisal.

### Recommended Value Range

Based on the 1,400-hour anchor estimate:

- **Conservative nonprofit-friendly value:** approximately **$120,000**
- **Fair-market senior independent builder value:** **\$140,000 to $175,000**
- **Small consultancy replacement-cost framing:** **\$175,000 to $245,000**

### Best Single-Number Anchor

For board-facing or partnership discussion:

> **Estimated in-kind software system design and development contribution to date: approximately $150,000.**

### Framing Guidance

Recommended wording:

> Estimated in-kind software system design and development contribution to date: approximately $150,000, based on roughly 1,400 hours of architecture, implementation, testing, and deployment preparation valued at a conservative fair-market professional rate.

### Practical Recommendation

Use one of these depending on the tone desired:

- **$120,000** for a conservative internal number
- **$150,000** as the best all-around fair-market anchor
- **\$150,000 to $175,000** if emphasizing realistic replacement value

### Important Caution

Describe the figure as:

> **an internal estimated fair-market value of in-kind technical services**

Do **not** describe it as a tax appraisal unless handled formally by the appropriate professional process.

---

## 5. Estimated Remaining Timeline

### Rough Remaining Time

A reasonable estimate for finishing, tuning, and polishing from the present state is:

- **4 to 8 months total**
- **6 months is a fair middle estimate**

### Why Six Months Sounds Realistic

The likely remaining work is the kind that usually takes longer than expected:

- polishing operator workflows
- sanding down stale routes and awkward seams
- tightening deployment and backup procedures
- cleaning test-harness drift
- hardening admin/control surfaces
- filling in edge cases
- improving seeds, fixtures, and real-world data handling
- refining documentation and successor-proofing
- addressing beta feedback from actual use

### Hours-Based View

The more important question is often hours per week rather than calendar duration.

#### Likely fit by weekly pace

- **5–8 hours/week:** 6 months is probably optimistic
- **8–12 hours/week:** 6 months is very plausible
- **15+ hours/week:** likely faster than 6 months if scope stays disciplined

### Estimated Remaining Manhours

- **250–500 hours** for a solid, practical finish
- **500–800 hours** if standards keep rising and additional nice-to-haves become must-haves

### Working Summary

A useful self-warning:

> Six months to finish, unless nice-to-haves keep being promoted into must-haves.

---

## 6. Finish-Line Fence

### Definition of “Done”

For this project, done should mean:

> A small nonprofit can safely operate the system for its core mission, on real hardware, with understandable runbooks, without needing constant developer babysitting.

Done does **not** mean:

- perfect
- elegant everywhere
- permanently feature-complete
- immune to every edge case

That is the fence.

---

## 7. Must Finish Before Calling It Done

These items define the minimum trustworthy operating state.

### 1. Core Operator Path Must Be Boring and Reliable

The main mission flow should work cleanly from end to end:

- operator login
- entity creation
- customer intake / verification
- needs assessment
- resource referral where applicable
- logistics issuance where applicable
- ledger/history trail visible
- basic admin oversight for exceptions

Test standard:

- normal happy path works
- common correction path works
- duplicate/stale-submit path does not cause damage

### 2. Deployment Must Be Repeatable

A clear deployment recipe must exist and be proven.

Required elements:

- server layout finalized
- writable vs read-only paths finalized
- Apache/mod_wsgi config finalized
- service management finalized
- backup procedure documented
- restore procedure at least sketched and partly proven
- smoke-check checklist after deployment

Test standard:

- the app can be rebuilt or redeployed without inventing steps from memory

### 3. Authentication and Authorization Must Be Trustworthy

Required elements:

- login/logout/change-password works
- operator onboarding works
- role gating works on real routes
- stale or dead privileged routes are removed or disabled
- route access sweep is current and documented

Test standard:

- no important surface is accidentally open
- no critical operator surface is silently unreachable

### 4. Admin/Control Surfaces Must Be Good Enough for Maintenance

Required elements:

- operator maintenance path works
- admin inbox/review flows that truly matter are live
- policy/admin tasks have a real place to happen
- stale admin placeholders are completed or removed

Test standard:

- no fake “coming soon” surface pretends to be operational

### 5. Data Integrity and Audit Trail Must Be Dependable

Required elements:

- ledger writes are consistent on important mutations
- customer/resource history behavior is intentional
- no PII leaks into ledger or logs
- actor identity remains consistent across a session
- critical write paths are covered by tests

Test standard:

- important actions are observable
- failures do not create mystery-state

### 6. Test Suite Must Be Credible

Required elements:

- full suite runs green
- stale tests are removed or repaired
- seed/bootstrap behavior no longer bloats runs uncontrollably
- core path regression tests exist
- key smoke tests are in place where needed

Test standard:

- a green test suite actually means something

### 7. Successor Runbook Must Exist

At minimum it should cover:

- app purpose and scope
- system shape
- slice responsibilities
- deployment/update steps
- backup expectations
- route sweep usage
- seeding/dev-test caveats
- known unfinished areas
- “what to check first” in an emergency

Test standard:

- a reasonably smart successor can get oriented without psychic powers

---

## 8. Should Finish Before Done

These items materially improve quality but do not all need to block launch.

### 1. UI Sanding and Consistency

- button/link placement consistency
- better overview pages
- clearer status badges
- fewer awkward navigation dead ends
- more obvious next-action affordances

### 2. Seed Data and Fixtures Improvement

- better demo data
- useful resource providers
- more realistic onboarding examples
- fewer brittle dev/test assumptions

### 3. Better Admin Diagnostics

- clearer anomaly reporting
- more useful maintenance screens
- easier visibility into policy/config state
- friendlier system health checks

### 4. Route and Surface Cleanup

- remove stale routes
- remove dead helpers
- remove compatibility shims
- reduce circular import traps and integration weirdness

### 5. Better Reporting and Read-Only Views

- operator summaries
- history browsing
- cleaner sponsor/resource/customer context pages
- practical audit views for humans

---

## 9. Can Wait Until Post-Launch

This is the anti-rabbit-hole bucket.

### 1. Fancy UX Improvements

- beautiful layout polish
- advanced dashboards
- lovely microcopy everywhere
- elegant empty states everywhere

### 2. Broad Analytics and Reporting Suite

- advanced rollups
- pretty charts
- board-facing dashboards
- deep management reports

### 3. Complex Automation

- scheduled jobs beyond essentials
- advanced inbox automation
- smart routing/escalation engines
- clever policy builders beyond MVP need

### 4. Full Edge-Case Conquest

- every obscure branch
- every rare concurrency oddity
- every future feature hook
- every hypothetical import or migration scenario

### 5. Architectural Perfectionism

- refactoring stable code because a prettier idea appears
- renaming things that already work
- polishing internal seams with no operator impact

---

## 10. Red-Flag Rabbit Holes

When one of these appears, stop and ask:

> Does this improve mission readiness before launch?

Common traps:

- rebuilding a slice because a prettier design now exists
- over-expanding Admin into a super-slice
- over-engineering policy editing
- chasing rare cadence edge cases too early
- broad test-harness rewrites during feature stabilization
- polishing non-core templates before deployment is locked
- adding new workflows because they would be nice

---

## 11. Practical Completion Checklist

Green light to call the project done when all of the following are true:

- core operator workflow works end to end
- deployment is proven and documented
- auth and role gating are trustworthy
- admin surfaces needed for real operation exist
- ledger/history behavior is dependable
- full test suite is green and credible
- successor runbook is usable
- known limitations are written down honestly

If those are true, the system is allowed to be called done.

---

## 12. Recommended Finishing Order

A sane finishing sequence for the remaining months:

1. **Core workflow gaps and stale surface cleanup**
2. **Deployment and backup proof**
3. **Auth/admin/control-surface hardening**
4. **Test harness credibility cleanup**
5. **Runbook and successor documentation**
6. **Cosmetic polish only after the system has earned it**

---

## 13. One-Sentence Anti-Rabbit-Hole Rule

Use this whenever the urge to wander appears:

> **Does this change make the nonprofit safer, more operable, or more maintainable before launch?**

If the answer is no, it probably belongs in the post-launch bucket.

---

## 14. Bottom-Line Summary

### Current Project Value

- **Estimated labor to current state:** about **1,400 hours**
- **Estimated fair-market in-kind value:** about **$150,000**

### Remaining Work

- **Estimated finish window:** about **6 months**
- **Likely remaining effort:** about **250–500 hours** for a practical finish, more if standards continue to rise

### Launch Discipline

The project should be considered done when it is:

- operationally safe
- deployable and restorable
- understandable by a successor
- trustworthy in its core mission paths

Not when it is perfect.
