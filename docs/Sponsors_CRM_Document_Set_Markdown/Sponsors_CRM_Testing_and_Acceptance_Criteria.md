# Sponsors CRM — Testing and Acceptance Criteria

## Purpose

This document explains what Sponsors CRM behaviors should be protected by
tests and what counts as acceptable workflow behavior.

It is intended to support safe refactoring and future enhancement.

## Testing philosophy

Sponsors CRM should be tested for:
- workflow integrity
- slice-boundary discipline
- operator-facing usefulness
- signal handling
- explicit actions

It should not be over-optimized for abstract internals that do not
matter to real operator workflow.

## Current workflow behaviors that should remain green

### CRM factor storage and posture
Protect:
- factor storage
- posture snapshot handling
- posture read behavior
- projection/index support
- patch/update flows
- derivation flows

### Advisory opportunity matching
Protect:
- published demand context consumption
- advisory match generation
- reasons/cautions/note hints presence
- stable, understandable sorting behavior
- no local invention of governance semantics

### Cultivation task creation
Protect:
- sponsor-linked cultivation task creation
- demand-linked cultivation task creation
- standing cultivation project usage
- readable operator-facing workflow behavior

### Outcome signal return and interpretation
Protect:
- Calendar → Sponsors outcome seam
- note capture and signal visibility
- sponsor-centered recent cultivation visibility
- demand-centered recent cultivation visibility

### Relationship knowledge promotion
Protect:
- promotion action works
- promotion is idempotent
- sponsor knowledge is preserved correctly
- duplicate promotion does not create a mess

### Follow-up cultivation task creation
Protect:
- discrete follow-up route works
- only valid source outcome rows can seed follow-up
- sponsor ownership guard holds
- funding demand linkage carries forward
- prior-touch summary carries forward

## Acceptance criteria for the current MVP

A change is acceptable if it preserves the following practical outcomes:

1. An operator can review a funding opportunity and see plausible sponsor
   matches
2. The operator can understand reasons and cautions without reading raw
   internals
3. The operator can create a cultivation task from that context
4. A completed cultivation task can return usable outcome signals
5. The operator can create a follow-up task from a completed outcome
6. The operator can preserve durable sponsor knowledge from an outcome
7. The sponsor detail page remains usable as a practical dossier
8. The demand page remains usable as a practical ask-centered workspace

## Boundary assertions that should remain true

Tests and reviews should verify that:
- Sponsors does not become money truth
- Sponsors does not become scheduling truth
- Sponsors does not invent governance semantics locally
- Calendar does not auto-interpret sponsor posture
- hidden automation does not mutate sponsor state silently

## UI acceptance criteria

A Sponsors CRM page should:
- expose next actions clearly
- avoid duplicate main actions in the same row
- keep cue language human-readable
- avoid raw-debug clutter
- remain understandable to a novice operator

## Regression risks

These are the common failure patterns to watch for:

### Cross-test state pollution
Because sponsor and demand fixtures may look similar across tests,
queries should use unique per-test identifiers where needed.

### Duplicate action rendering
Templates may accidentally repeat action buttons inside nested lists or
loop blocks.

### Over-interpretation of signals
It is easy for new features to start treating Calendar signals like
commands or truth. That should be resisted.

### Hidden posture mutation
Future code must not silently change sponsor posture without an explicit,
traceable operator action.

### Boundary creep
A useful read-only summary can easily become an accidental second source
of truth. This should be avoided.

## Review checklist for future changes

Before accepting a Sponsors CRM change, ask:
1. Does this improve real operator workflow?
2. Does it preserve slice boundaries?
3. Does it keep human judgment in control?
4. Does it remain readable to a novice?
5. Does it avoid turning the page into a debug panel?
6. Does it avoid corporate-CRM theater?

If the answer to those questions is mostly yes, the change is likely
aligned.

## Suggested future test additions

As the CRM grows, likely future tests should cover:
- sponsor next-touch summary derivation
- needs-attention queue behavior
- relationship stage edits if added
- stewardship reminder workflows
- support history read-only summaries sourced from Finance seams
