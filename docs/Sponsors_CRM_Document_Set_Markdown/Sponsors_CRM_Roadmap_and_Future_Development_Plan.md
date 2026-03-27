# Sponsors CRM Roadmap and Future Development Plan

## Purpose

This document captures the current state of the Sponsors CRM capability in VCDB v2, defines the intended product direction, and lays out a staged roadmap for continued development. It is written to serve both as a planning aid for current development and as a future-dev handoff document in the event work must be paused or transferred.

The goal is not to build a bloated or overly clever donor-management system. The goal is to build a practical, operator-friendly relationship management tool that helps staff understand sponsors, maintain relationship continuity, and take the right next action at the right time.

---

## Current State of Play (MVP Baseline)

Sponsors CRM currently exists as an advisory and workflow layer on top of the Calendar → Sponsors funding-context seam.

### Implemented baseline

- Sponsors consumes the published Calendar funding-context packet.
- Realization defaults are context-aware and packet-backed.
- Restriction merging is hardened and uses packet + fund defaults rather than inventing semantics locally.
- Sponsor-local CRM taxonomy exists in `taxonomy_crm.py`.
- CRM posture snapshot storage exists in `SponsorHistory.section = "sponsor:crm_factors:v1"`.
- Query projection exists in `SponsorCRMFactorIndex`.
- Storage, read models, patch/update flows, and derivation flows are in place.
- Opportunity matching exists and remains advisory-first.
- Funding opportunity detail shows sponsor matches, reasons, cautions, note hints, suggested next actions, and cultivation context.
- Sponsor detail shows CRM posture, profile note hints, cultivation activity, and operator actions.
- Staff-facing CRM factor editing exists and is operational.
- Sponsors can create Calendar cultivation tasks under the standing Calendar project `Sponsor Cultivation`.
- Cultivation tasks can optionally carry `funding_demand_ulid`.
- Calendar returns recent cultivation outcome signals back to Sponsors over a clean contract seam.
- Sponsors can promote a cultivation outcome note into sponsor relationship knowledge.
- Promotion is idempotent and tested.
- Staff can create a follow-up cultivation task from a completed cultivation outcome.
- Funding opportunity detail now shows recent cultivation activity relevant to a funding demand.
- Operator-facing cue surfaces exist in light form and remain advisory.

### Current design posture

- **Sponsors owns relationship interpretation.**
- **Calendar owns scheduled work and outcome capture.**
- **Finance remains money truth.**
- **Governance remains semantic authority.**
- **Automation remains light.** The system should surface cues and next actions, not silently mutate relationship state.

### MVP assessment

The current Sponsors CRM capability should be considered an **effective MVP**.

It already provides:

- relationship memory,
- opportunity-to-sponsor visibility,
- explicit cultivation task creation,
- outcome capture,
- follow-up support,
- operator-centered workflow.

That is enough to make the tool genuinely useful in day-to-day work. The next steps should focus on depth, clarity, continuity, and operator support rather than algorithmic cleverness.

---

## Product Vision

Sponsors CRM should become three practical things:

### 1. Sponsor dossier

A working relationship file that tells staff:

- who this sponsor is,
- what they tend to support,
- what has happened with them,
- what has been learned,
- what should happen next.

### 2. Work queue

A clean operator-facing queue that answers:

- who needs attention,
- why they need attention,
- what follow-up is due,
- what demand or workflow the contact relates to.

### 3. Ask context

A demand-centered view that helps staff understand:

- which sponsors appear relevant,
- who has already been contacted,
- what those contacts produced,
- whether follow-up is needed,
- where the demand stands in relation to sponsor outreach.

This should remain an **operator support system**, not a donor prediction engine.

---

## Core Design Principles

The following should remain true as Sponsors CRM evolves.

### Operator judgment over automation

The system should surface cues, reminders, and recommended next actions, but leave relationship interpretation and decision-making to staff.

### Explicit actions over hidden state changes

The operator should be able to see the cue, understand the reason, and click a clear action. Silent posture changes or inferred relationship updates should be avoided.

### Readable workflow over abstraction theater

Views, actions, and summaries should help a staff member work the relationship. The page should feel like a practical desk tool, not a debug panel or a machine-learning demo.

### Strong slice boundaries

- Calendar schedules work and records outcomes.
- Sponsors interprets those outcomes.
- Finance remains authoritative for money.
- Governance remains authoritative for semantic rules.

### Notes remain important

Structured CRM fields are helpful, but freeform relationship notes remain essential. Sponsor work is human work. The system must preserve room for nuance.

---

## Recommended Development Stages

## Stage 0 — Present Baseline (Completed / In Place)

This stage is effectively complete.

### Delivered capabilities

- CRM posture storage and projection.
- Advisory sponsor matching against funding opportunities.
- Cultivation task creation from Sponsors into Calendar.
- Calendar outcome feedback into Sponsors.
- Promotion of useful outcome notes into relationship knowledge.
- Follow-up task creation from completed outcome rows.
- Demand-centered recent cultivation visibility.
- Light operator cue surfaces.
- Initial sponsor dossier polish.

### Why this matters

This stage established the core loop:

**Opportunity → Sponsor review → Cultivation task → Outcome → Relationship learning → Follow-up**

That loop is the foundation Sponsors CRM needed.

---

## Stage 1 — Workflow Strengthening (Recommended Next)

This stage should make day-to-day sponsor work clearer, more consistent, and easier to resume after interruptions.

### Features

#### 1. Sponsor-level next-touch summary

Add a compact sponsor-level summary block showing:

- next touch due date,
- next touch purpose,
- linked demand if any,
- why this touch matters,
- last outcome summary.

This should be a **summary of active work**, not a replacement for Calendar tasks.

#### 2. Standard cultivation outcome types

Add a small controlled pick-list alongside freeform notes.

Suggested values:

- no response
- interested
- interested, needs more info
- declined
- declined for now
- asked to reconnect later
- referred elsewhere
- stewardship touch completed
- ask discussion advanced

The note should remain required or strongly encouraged. The type is there for reporting and filtering.

#### 3. Relationship stage

Add a sponsor-level, operator-managed relationship stage.

Suggested values:

- unknown
- researching
- initial outreach
- engaged
- active cultivation
- considering ask
- pending follow-up
- active supporter
- cooling off
- dormant

This should be **manually set or manually confirmed**, not silently derived.

#### 4. Contact strategy fields

Improve sponsor contact clarity.

Suggested fields or note surfaces:

- primary contact,
- alternate contact,
- title/role,
- preferred contact method,
- best route in,
- intro source,
- communication sensitivity notes.

#### 5. Light reminder logic

Add advisory cues for:

- follow-up overdue,
- strong interest with no follow-up scheduled,
- sponsor untouched for too long,
- off-cadence follow-up flagged,
- likely sponsor with no cultivation activity on active demand.

These should remain **non-blocking prompts**.

### Likely refits

- Sponsor detail layout will likely need another pass once next-touch summary is introduced.
- Calendar outcome forms may need a modest refit to support outcome type selection.
- Sponsors taxonomy and storage may need a new posture/history version for relationship stage.
- Demand pages may need a clearer relationship between “last touch” and “next touch.”

---

## Stage 2 — Queue and Continuity Tools

This stage should help operators manage sponsor work in aggregate rather than one page at a time.

### Features

#### 1. Needs-attention queue

A simple queue showing sponsors or demand-linked relationships that need review.

Entry reasons may include:

- follow-up overdue,
- follow-up recommended,
- off-cadence follow-up signal,
- funding interest surfaced,
- no touch in X days,
- cultivation active but no resolution,
- promising demand match with no outreach yet.

This is likely one of the highest-value additions.

#### 2. My work / unowned work views

Depending on staffing patterns, add views for:

- relationships assigned to me,
- unassigned sponsor follow-ups,
- stale/open cultivation tasks,
- recent sponsor activity requiring review.

If staff ownership is not yet formalized, this can begin as a generic queue.

#### 3. Relationship owner

If operationally useful, add a simple concept of relationship owner or current responsible staff member.

This should answer:

- who owns the relationship,
- who made the last touch,
- who should make the next one.

#### 4. Queue triage actions

Allow direct actions from the queue:

- schedule follow-up,
- review sponsor dossier,
- review CRM posture,
- jump to linked demand,
- mark reviewed / defer.

### Likely refits

- Sponsor detail page may need a summarized header vs full dossier body separation.
- Calendar task reads may need additional queue-friendly DTOs.
- Sponsor activity summarization may benefit from a reusable mapper or view model.
- Operator permissions and visibility may need refinement if assignment/ownership is introduced.

---

## Stage 3 — Stewardship and Support Memory

This stage broadens CRM beyond cultivation into durable sponsor relationship management.

### Features

#### 1. Stewardship tracking

Track whether the sponsor has received appropriate follow-through after support.

Examples:

- thank-you sent,
- update/report sent,
- acknowledgment delivered,
- board recognition needed,
- compliance/reporting follow-up due.

#### 2. Ask history and support summary

Provide a sponsor-facing summary of what has worked before.

Examples:

- prior realized support,
- support by type,
- typical restriction pattern,
- last successful support date,
- demand categories historically supported.

Finance remains the authoritative money source, but Sponsors should provide readable context.

#### 3. Soft relationship memory

Track important handling notes such as:

- do not contact too often,
- prefers concise asks,
- board review takes time,
- email first,
- local-veterans only,
- avoid year-end unless invited.

This is often some of the highest-value relationship knowledge in a real CRM.

#### 4. Sponsor engagement history timeline

Expand the dossier timeline so it includes:

- CRM factor changes,
- cultivation actions,
- outcome promotions,
- stewardship actions,
- support history summaries,
- significant relationship notes.

### Likely refits

- Sponsor detail page may need tabs or section anchors to stay usable.
- Sponsors ↔ Finance read seams may need additional summary DTOs.
- Calendar may need stewardship task conventions if stewardship is scheduled there.
- Taxonomy may need a stewardship/status extension.

---

## Stage 4 — Formal Ask Support

This stage helps staff prepare more disciplined asks without turning the system into corporate fundraising software.

### Features

#### 1. Ask preparation checklist

For formal asks, track readiness items like:

- problem statement ready,
- amount defined,
- restrictions reviewed,
- linked demand clear,
- support docs prepared,
- reporting expectations understood.

#### 2. Ask packet support

Provide a structured page or section that gathers:

- sponsor fit,
- demand context,
- known restrictions,
- prior relationship notes,
- key cautions,
- ask amount,
- follow-up plan.

#### 3. Ask outcome memory

Track whether an ask:

- advanced,
- stalled,
- was declined,
- needs revision,
- should be revisited later.

This should remain practical and light.

### Likely refits

- Opportunity detail pages may need a clearer shift from “matching” to “preparing ask.”
- Sponsors taxonomy may need ask-stage and ask-outcome concepts.
- Documents/attachments strategy may need to be clarified if formal ask packets are stored.

---

## Stage 5 — Reporting and Administrative Durability

This stage exists to support continuity, leadership review, and future maintainers.

### Features

#### 1. Sponsor CRM reporting

Useful reports may include:

- sponsors needing attention,
- sponsors with surfaced interest,
- no-touch aging,
- relationship stage distribution,
- outcome type distribution,
- demand-to-cultivation conversion visibility,
- follow-up completion timing.

#### 2. Admin configuration and taxonomy management

If the CRM taxonomy grows, it may need admin-friendly editing or validation tooling.

#### 3. Audit and diagnostics

Provide support tools for reviewing:

- missing sponsor links,
- orphaned cultivation records,
- stale next-touch summaries,
- invalid stage values,
- queue drift.

#### 4. Future-dev documentation package

Maintain library docs describing:

- CRM field meanings,
- workflow rules,
- queue semantics,
- stewardship semantics,
- stage definitions,
- known refit points,
- slice boundary rules.

### Likely refits

- Reporting surfaces may benefit from reusable projections instead of page-specific query logic.
- Admin support may require controlled schema/taxonomy editing patterns.
- Queue/report logic may need normalization into dedicated services.

---

## Feature Catalog and Priority Guidance

Below is a practical feature inventory with recommended priority.

### High-value / near-term

- Sponsor-level next-touch summary
- Standard cultivation outcome types
- Relationship stage
- Needs-attention queue
- Sponsor dossier timeline refinement
- Contact strategy / best-route-in notes
- Reminder cues for stale sponsor relationships

### Medium-term

- Relationship owner / assignment
- Stewardship tracking
- Ask/support summary from Finance reads
- Queue triage actions
- Simple ask-readiness checklist

### Later / optional

- Formal ask packet workflow
- Rich CRM reports
- Admin taxonomy editing tools
- More nuanced assignment/workload management

### Avoid or defer

These should remain explicitly deferred unless a real operational need appears:

- predictive scoring,
- probability-of-giving fields,
- auto-updating relationship posture,
- aggressive automation,
- large funnel dashboards,
- over-structured note systems,
- required-data bloat.

---

## Recommended Build Order

A practical build order from this point forward:

1. Sponsor-level next-touch summary
2. Standard cultivation outcome types
3. Relationship stage
4. Needs-attention queue
5. Dossier timeline cleanup and refinement
6. Contact strategy enhancements
7. Stewardship tracking
8. Ask/support summary from Finance
9. Queue triage actions
10. Formal ask support
11. Reporting and admin durability work

This sequence keeps the work grounded in operator value and preserves the current lightweight architecture.

---

## Expected Refit Areas by Slice

## Sponsors slice

Likely future refits:

- sponsor detail/dossier layout,
- CRM posture model or versioning,
- relationship stage storage,
- next-touch summary storage/projection,
- queue-oriented projections,
- support-history summary rendering,
- stewardship surfaces.

## Calendar slice

Likely future refits:

- cultivation outcome capture additions,
- stewardship task conventions,
- queue-friendly outcome DTOs,
- maybe standardized outcome-type storage,
- possibly more explicit task-purpose conventions.

Calendar should continue to avoid interpreting sponsor meaning.

## Finance slice

Likely future refits:

- read-only sponsor support history summaries,
- last support date / support pattern views,
- summary DTOs that Sponsors can consume without leaking Finance internals.

Finance should remain money truth.

## Governance slice

Likely future refits:

- minimal, if any, for CRM itself,
- possible semantic controls if stewardship/reporting categories need canonical semantics,
- possible policy guidance for sponsorship restrictions or reporting requirements.

Governance should not become relationship memory.

## Extensions / Contracts

Likely future refits:

- additional Calendar read DTOs,
- sponsor support-history summary contracts,
- queue/report-oriented contract surfaces,
- possibly contact/assignment reads if those become cross-slice concerns.

---

## Risks and Anti-Patterns

The following are the most likely failure modes as Sponsors CRM grows.

### 1. Over-automation

If the app begins silently changing relationship state, operators will stop trusting it.

### 2. Page sprawl

If sponsor detail and funding opportunity pages become action dumps, usability will degrade fast.

### 3. Too many fields too early

CRM systems become hated when staff spend more time feeding the system than using it.

### 4. Hidden semantics

Outcome signals, relationship stage, queue reasons, and next-touch logic should remain understandable and inspectable.

### 5. Slice leakage

Sponsors must not drift into becoming a scheduling engine or a finance truth source.

---

## What “Good” Looks Like

Sponsors CRM is succeeding when a staff member can open the system and quickly answer:

- Who is this sponsor?
- What do they care about?
- What happened last?
- What should I do next?
- What demand or relationship context matters right now?

That is the standard to measure future features against.

Any feature that helps answer those questions is likely worth building.
Any feature that does not should be treated with caution.

---

## Future-Dev Handoff Notes

If a future developer or maintainer picks this up, the immediate understanding should be:

1. The Sponsors CRM MVP is already operational and valuable.
2. The next work should emphasize continuity, readability, and queue discipline.
3. The system is intentionally not trying to be a donor prediction platform.
4. Slice boundaries matter and should not be blurred for convenience.
5. The highest-value next feature is probably a **needs-attention queue** supported by light sponsor-level summary fields.

### Suggested handoff packet

Future Dev should have access to:

- this roadmap,
- current Sponsors CRM taxonomy documentation,
- route map for sponsor detail and funding opportunity detail,
- cultivation task creation and follow-up flow notes,
- Calendar cultivation outcome contract notes,
- test suite pointers for sponsor CRM workflow coverage.

---

## Suggested Documentation Companions

This roadmap should eventually sit beside a small documentation set:

- `Sponsors CRM — Current Workflow.md`
- `Sponsors CRM — Taxonomy and Field Meanings.md`
- `Sponsors CRM — Queue Semantics.md`
- `Sponsors CRM — Dossier Layout Notes.md`
- `Sponsors CRM — Future Refit Watchlist.md`

That package would make future maintenance much easier.

---

## Closing Position

Now is the correct time to write this down.

The current state is clear, the MVP is operational, the feature boundaries are visible, and the likely refits can still be seen before they become buried under later decisions.

This roadmap should be treated as the working development guide for Sponsors CRM until replaced by a more formal product/architecture document.
