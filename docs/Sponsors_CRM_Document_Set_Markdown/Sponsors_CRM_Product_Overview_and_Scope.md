# Sponsors CRM — Product Overview and Scope

## Purpose

Sponsors CRM exists to support relationship-based sponsor cultivation
inside VCDB without turning the application into a corporate customer
relationship platform.

Its purpose is to help staff:
- understand sponsor fit for a given funding need
- remember what has been learned about a sponsor over time
- schedule and review cultivation work
- interpret recent cultivation outcomes
- decide on the next appropriate human action

The system is intended to support **human judgment**, not replace it.

## Scale assumptions

The present operating environment is:
- local community scale
- modest budget
- local small businesses and community partners
- relatively small asks
- small to moderate sponsor/prospect pool
- relationship memory and follow-up discipline matter more than scoring

These assumptions are important. They explain why VCDB favors:
- explicit operator controls
- readable pages
- cultivation queues
- practical notes and signals
- small, understandable workflow steps

and avoids:
- automated relationship scoring
- machine-derived sponsor posture
- overfit dashboards
- enterprise sales-pipeline abstractions

## What Sponsors CRM is

Sponsors CRM is a relationship-memory and next-action support layer built
inside the Sponsors slice.

In practical terms, it provides:
- sponsor-local CRM factor storage
- sponsor posture read models
- advisory funding opportunity matching
- sponsor profile note hints
- Calendar-backed cultivation tasks
- returned cultivation outcome signals
- follow-up creation from completed outcomes
- demand-centered cultivation visibility
- operator cues for review and next steps

## What Sponsors CRM is not

Sponsors CRM is not:
- the source of truth for money movement
- the source of truth for scheduling internals
- the authority on governance semantics
- a donor prediction engine
- a corporate sales platform
- an automated relationship-temperature engine

Those responsibilities remain elsewhere:
- Finance owns money truth
- Calendar owns scheduled work and outcome capture
- Governance owns semantic authority
- Sponsors owns relationship interpretation

## Current MVP baseline

The current MVP and immediate enhancement passes establish the following:

### Sponsor relationship memory
- Sponsor-local CRM taxonomy exists in `taxonomy_crm.py`
- CRM posture snapshots are stored in Sponsor History
- query projections exist for CRM posture use
- patch/update/derivation flows are in place and tested

### Advisory matching
- Sponsors consumes the published Calendar funding-context packet
- opportunity matching is advisory-first
- funding opportunity detail pages show sponsor matches, reasons,
  cautions, note hints, and suggested next action

### Sponsor dossier / operator workspace
- sponsor detail pages show CRM posture
- sponsor detail pages show profile note hints
- sponsor detail pages show recent cultivation activity
- operators can edit CRM factors through a staff-facing surface

### Calendar cultivation seam
- Sponsors can create cultivation tasks under the standing
  `Sponsor Cultivation` Calendar project
- cultivation tasks can carry `funding_demand_ulid`
- Calendar returns recent cultivation outcome signals through a clean
  contract seam
- Sponsors can promote a cultivation outcome note into relationship
  knowledge
- promotion is idempotent and tested

### Follow-up and demand visibility
- operators can create a follow-up cultivation task from a completed
  cultivation outcome
- funding opportunity detail pages show recent cultivation activity
  relevant to the demand
- operator cues surface follow-up or interest signals without forcing
  posture changes

## Product goals

The near- and mid-term goals of Sponsors CRM are:

1. Preserve relationship memory across time and staff turnover
2. Improve follow-up discipline
3. Make funding-opportunity review more actionable
4. Keep sponsor detail pages useful as working dossiers
5. Preserve clear slice boundaries
6. Avoid unnecessary automation

## Guiding principles

### Human queues over automated “temperature”
Sponsor relationship “temperature” should be inferred by people from the
queue of recent events, notes, outcomes, and follow-up needs.

It should not be auto-derived by opaque logic.

### Signals over automation
Calendar should return what happened.
Sponsors should surface cues.
Operators should make decisions.

### Readability over cleverness
The best Sponsors CRM page is the page a novice operator can understand
without training deck archaeology.

### Practicality over abstraction
Features should be added because they improve actual sponsor work, not
because they resemble fashionable CRM products.

## Out of scope for the present phase

The following are deliberately out of scope for the current phase:
- automated posture mutation
- predictive sponsor scoring
- complex temperature engines
- large enterprise-style funnel analytics
- heavy-weight workflow automation
- speculative AI-like matching layers

## Success criteria

Sponsors CRM is succeeding when an operator can quickly answer:
- Who is this sponsor?
- Why might they fit this demand?
- What happened last time?
- What should happen next?
- Is follow-up pending?

without hunting across multiple slices or inventing informal memory
systems outside the app.
