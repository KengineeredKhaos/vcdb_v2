# Sponsors CRM Document Set

This document set supports the current Sponsors CRM MVP in VCDB and
provides a practical path for future development.

The intended audience is:
- current developers
- future developers
- operators or administrators trying to understand the workflow
- successors who may inherit the project without full project history

## Design posture

Sponsors CRM in VCDB is intentionally **not** a corporate sales platform.

It is designed for:
- local community work
- modest numbers of sponsors and prospects
- relatively small asks
- high-trust, relationship-based operator judgment
- explicit work queues and follow-up discipline

It is intentionally **not** designed around:
- automated sponsor “temperature” scoring
- predictive ranking engines
- posture automation
- opaque decisioning
- dashboard theater

The operating principle is simple:

> Calendar reports what happened. Sponsors interprets what it means.
> Operators decide what to do next.

## Current-state documents

1. [Sponsors CRM — Product Overview and Scope](./Sponsors_CRM_Product_Overview_and_Scope.md)
2. [Sponsors CRM — Operator Workflow Guide](./Sponsors_CRM_Operator_Workflow_Guide.md)
3. [Sponsors CRM — Slice Boundaries and Responsibility Map](./Sponsors_CRM_Slice_Boundaries_and_Responsibility_Map.md)
4. [Sponsors CRM — Taxonomy and Signal Glossary](./Sponsors_CRM_Taxonomy_and_Signal_Glossary.md)
5. [Sponsors CRM — UI Surface Map](./Sponsors_CRM_UI_Surface_Map.md)
6. [Sponsors CRM — Testing and Acceptance Criteria](./Sponsors_CRM_Testing_and_Acceptance_Criteria.md)

## Forward-plan documents

These are intentionally marked as evolving and should be treated as
planning references rather than frozen canon.

7. [Sponsors CRM — Future Refits Register](./Sponsors_CRM_Future_Refits_Register.md)

## Recommended reading order

For a new developer or successor:
1. Product Overview and Scope
2. Slice Boundaries and Responsibility Map
3. Operator Workflow Guide
4. UI Surface Map
5. Taxonomy and Signal Glossary
6. Testing and Acceptance Criteria
7. Future Refits Register

## Current MVP summary

At the time of writing, Sponsors CRM includes:
- sponsor-local CRM taxonomy
- CRM factor storage and read models
- advisory opportunity matching against published funding demands
- sponsor dossier/detail support for CRM posture and recent activity
- Calendar-backed cultivation task creation
- cultivation outcome signal return from Calendar into Sponsors
- promotion of outcome notes into sponsor relationship knowledge
- follow-up cultivation task creation from completed outcomes
- demand-centered cultivation visibility on funding opportunity pages
- operator-facing cues without automated posture mutation

## Core doctrine

Sponsors CRM should help staff answer five practical questions:
1. Who is this sponsor?
2. What do we know about them?
3. What happened most recently?
4. What needs to happen next?
5. When should that happen?

If a proposed feature does not improve those answers, it should be
considered carefully before being added.
