# Sponsors CRM — Slice Boundaries and Responsibility Map

## Purpose

This document defines the responsibility boundaries relevant to Sponsors
CRM. It exists to prevent the CRM layer from absorbing responsibilities
that belong to other slices.

The CRM layer is useful precisely because it stays disciplined.

## Core rule

Sponsors CRM is a relationship-interpretation layer.

It is **not** the owner of all sponsor-adjacent data or behavior.

## Responsibility map

### Sponsors slice
Sponsors owns:
- sponsor-local CRM taxonomy
- CRM factors and posture snapshots
- sponsor profile note hints
- advisory opportunity matching
- interpretation of cultivation signals
- sponsor dossier presentation
- demand-centered relationship visibility
- operator workflow actions related to sponsor interpretation

Sponsors does **not** own:
- authoritative scheduling internals
- money posting or reserve truth
- governance policy semantics
- general-purpose workflow automation

### Calendar slice
Calendar owns:
- projects and tasks
- cultivation work scheduling
- task status progression
- task due/completion timing
- outcome capture structure
- read seams exposing cultivation outcomes

Calendar reports what happened.
Calendar does not decide what sponsor relationship meaning should be
assigned to those events.

### Finance slice
Finance owns:
- receipts
- reserve handling
- encumbrance/spend truth
- posting behavior
- monetary history and audit truth

Sponsors may display read-only support history or context in the future,
but it must not become the system of record for money events.

### Governance slice
Governance owns:
- semantic authority
- policy-defined categories and controls
- finance and funding semantics
- board-level or policy-level constraints

Sponsors may consume governance-shaped context, but must not invent
parallel policy semantics.

## Current seam: Calendar cultivation outcomes

The present Sponsors ↔ Calendar seam is intentionally simple.

### Sponsors sends to Calendar
- sponsor identity
- optional `funding_demand_ulid`
- workflow = cultivation
- advisory match context
- task purpose / next action context

### Calendar returns to Sponsors
- `task_ulid`
- `project_ulid`
- `sponsor_entity_ulid`
- `workflow`
- `status`
- `task_title`
- `due_at_utc`
- `done_at_utc`
- `funding_demand_ulid`
- `outcome_note`
- `follow_up_recommended`
- `off_cadence_follow_up_signal`
- `funding_interest_signal`

Calendar returns signals.
Sponsors interprets signals.

This seam should remain disciplined.

## Interpretation boundary

Sponsors may:
- show operator cues
- show recent cultivation activity
- suggest next actions
- create explicit follow-up tasks
- promote notes into relationship knowledge

Sponsors should not:
- auto-change CRM posture based on signals
- auto-score sponsor temperature
- auto-conclude sponsor intent
- silently mutate sponsor state without operator action

## Queue boundary

The correct model for sponsor relationship assessment is a **human queue**:
- recent touches
- recent outcomes
- pending follow-up
- relationship notes
- demand-linked activity

This queue helps humans determine sponsor “temperature.”

It should not be replaced by an automated hidden posture engine.

## Page ownership implications

### Sponsor detail page
This page is sponsor-centered and interpretive.
It may combine:
- sponsor CRM factors
- recent cultivation activity
- preserved relationship knowledge
- operator workflow actions

### Funding opportunity detail page
This page is demand-centered and interpretive.
It may combine:
- sponsor matches
- reasons and cautions
- demand-linked cultivation activity
- explicit cultivation actions

### Calendar task pages
These remain Calendar-owned scheduling surfaces.

### Finance pages
These remain Finance-owned monetary truth surfaces.

## Allowed future growth

The following future additions are compatible with these boundaries:
- sponsor next-touch summary in Sponsors
- sponsor relationship stage as an operator-set field
- demand queue views in Sponsors
- stewardship reminders represented through explicit tasks
- read-only support history summaries sourced from Finance seams

## Boundary violations to avoid

Future development should avoid:
- storing money truth in Sponsors
- teaching Calendar to derive sponsor posture
- duplicating governance semantics locally in Sponsors
- building hidden automation that changes relationship status
- turning sponsor detail into a de facto scheduling database

## Summary doctrine

Use this sentence as the test:

> Calendar owns work. Finance owns money. Governance owns semantics.
> Sponsors owns relationship interpretation.

If a proposed feature violates that sentence, it needs redesign.
