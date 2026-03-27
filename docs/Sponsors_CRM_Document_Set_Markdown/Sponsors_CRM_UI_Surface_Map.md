# Sponsors CRM — UI Surface Map

## Purpose

This document maps the current Sponsors CRM UI surfaces and explains what
each page is for.

It is intended to help developers understand page responsibility and to
help future redesign work remain disciplined.

## Design doctrine

Every Sponsors CRM page should answer a practical operator question.

If a page starts to feel like a debug panel, a spreadsheet dump, or a
corporate dashboard imitation, it should be revisited.

## Current core surfaces

### 1. Sponsor detail page

**Orientation:** sponsor-centered dossier

**Purpose:** provide a practical working view of a sponsor as a
relationship.

**Current responsibilities:**
- show CRM posture
- show profile note hints
- show recent cultivation activity
- show latest cultivation touch
- show operator workflow actions
- provide note-promotion and follow-up creation actions
- link back to relevant demand context when applicable

**Operator questions answered here:**
- what do we know about this sponsor?
- what happened most recently?
- what should happen next?
- do I need to preserve this note or schedule follow-up?

**Design direction:**
This page should evolve toward a dossier, not a cluttered task dump.

Recommended long-term sections:
- sponsor summary
- operator workflow
- latest touch
- relationship notes
- recent demand-linked activity
- support history summary (read-only from Finance later)

### 2. Funding opportunity detail page

**Orientation:** demand-centered

**Purpose:** help operators evaluate sponsor options for a specific
funding need.

**Current responsibilities:**
- show sponsor matches
- show reasons, cautions, and note hints
- show suggested next action
- show demand-linked recent cultivation activity
- show whether follow-up is pending or already scheduled
- provide explicit cultivation task creation

**Operator questions answered here:**
- who looks promising for this demand?
- why do they look promising?
- who has already been contacted?
- what did the last touch produce?
- do we need follow-up?

**Important design note:**
This page should have one clear action zone per sponsor row.

Repeated or sprayed action buttons create confusion and should be
avoided.

### 3. CRM factor edit surface

**Orientation:** sponsor-centered editing

**Purpose:** allow staff to maintain sponsor CRM factors and posture
inputs.

**Current responsibilities:**
- edit sponsor-local CRM factors
- update the sponsor posture inputs that drive advisory views
- remain clear and staff-friendly

**Operator questions answered here:**
- how do I correct or improve what the system knows about this sponsor?

**Design caution:**
This page should remain operational and readable, not schema-first.

### 4. Cultivation action surfaces

These are action entry points embedded in sponsor or demand pages rather
than a separate giant screen.

**Current uses:**
- create cultivation task
- create follow-up cultivation task
- promote relationship knowledge from outcome note

**Design posture:**
These should remain explicit buttons and forms, not hidden automations.

## Current page relationships

### Sponsor detail → Funding opportunity
When a recent cultivation row references a demand, operators should be
able to navigate back to the relevant funding opportunity for context.

### Funding opportunity → Sponsor detail
Operators should be able to open the sponsor dossier from a demand row to
review broader relationship context before acting.

This two-way movement is important and should remain easy.

## UI anti-patterns to avoid

### Button spray
Do not repeat the same main action in multiple sublists inside a single
row or section.

### Debug-panel sprawl
Do not expose raw internal data just because it is available.

### Over-badging
Cues should help, not shout.

### Corporate funnel mimicry
The app is not trying to imitate a large-enterprise CRM product.

## Desired page qualities

Every Sponsors CRM page should be:
- simple
- readable
- approachable
- intuitive
- explicit about next actions
- grounded in real operator workflow

## Good future UI additions

Likely good additions:
- a sponsor-level next-touch summary box
- a needs-attention queue view
- a compact support history summary
- a clearer relationship note section
- a practical relationship stage display if later adopted

## Surface ownership reminder

These pages are interpretive Sponsors surfaces.

They should not absorb:
- Calendar’s scheduling authority
- Finance’s money truth
- Governance’s semantic authority
