# Sponsors CRM — Future Refits Register

## Status

This document is a planning document.
It is intentionally **forward-looking** and should not be mistaken for
current implemented behavior.

Its purpose is to record likely future refinements while the current MVP
and early enhancement passes are still fresh in mind.

## Planning rule

Future refits should continue to honor these principles:
- human judgment stays primary
- queues matter more than scoring
- explicit actions matter more than automation
- slice boundaries stay clean
- the app remains small-scale, approachable, and intuitive

## Refit categories

## 1. Sponsor dossier refinement

### Why
The sponsor detail page is already evolving into a working dossier and
will likely continue to absorb the most useful relationship-memory
functions.

### Likely future work
- clearer sponsor summary header
- next-touch summary box
- cleaner relationship-note section
- more structured latest-touch summary
- compact demand-linked activity grouping
- optional read-only support history summary sourced from Finance

### Likely slice impact
- Sponsors templates and view shaping
- possible read-only Finance seam consumption later

## 2. Human queue / needs-attention view

### Why
As more cultivation work accumulates, operators will likely need a queue
showing what needs attention next.

### Likely queue triggers
- follow-up pending review
- follow-up overdue
- funding interest surfaced with no follow-up yet
- no sponsor touch for a long interval
- promising demand/sponsor match with no cultivation yet

### Important design note
This queue should remain queue-based and human-reviewed.
It should not become an automated “temperature” or probability engine.

### Likely slice impact
- Sponsors list/read surfaces
- light read-model additions or view helpers

## 3. Standard cultivation outcome categories

### Why
Outcome notes are useful, but a small controlled set of outcome types may
improve filtering and queue/reporting support.

### Candidate categories
- no response
- interested
- interested needs more info
- declined
- declined for now
- reconnect later
- stewardship touch
- commitment discussion

### Important caution
These should supplement notes, not replace them.

### Likely slice impact
- Calendar outcome capture surface
- Calendar ↔ Sponsors outcome seam
- glossary and operator docs

## 4. Sponsor next-touch summary

### Why
Operators often need one plain summary of what should happen next.

### Candidate fields
- next touch due
- next touch purpose
- why this is the next action
- linked demand, if any
- source of the recommendation

### Important design note
This should remain a readable summary, not a hidden decision engine.

### Likely slice impact
- Sponsors view logic
- possible explicit operator-set field or derived queue summary

## 5. Relationship stage (operator-set, not automated)

### Why
A lightweight relationship stage may help summarize overall sponsor
status.

### Candidate stages
- unknown
- researching
- initial outreach
- engaged
- active cultivation
- pending follow-up
- active supporter
- cooling off
- dormant

### Important design note
If adopted, this should be operator-set or operator-confirmed.
It should not be silently derived from task traffic.

### Likely slice impact
- Sponsors taxonomy
- sponsor edit surfaces
- sponsor dossier display
- docs and glossary

## 6. Stewardship support

### Why
A good CRM should also help remember appreciation and follow-through, not
just asks.

### Candidate future support
- thank-you reminder
- promised update reminder
- reporting follow-up reminder
- recognition / acknowledgement tracking
- stewardship note summaries

### Important design note
These should likely remain explicit tasks and notes, not separate hidden
states.

### Likely slice impact
- Calendar task patterns
- Sponsors operator views
- possible Finance read-only context

## 7. Contact-route clarity

### Why
At local scale, knowing the right person and preferred route often
matters more than sophisticated matching logic.

### Candidate future additions
- primary contact clarity
- alternate contact clarity
- preferred contact method
- warm-introduction source
- “best route in” note

### Likely slice impact
- Entity / sponsor-connected contact presentation
- sponsor dossier display

## 8. Reporting and operator review summaries

### Why
Operators and future administrators may want simple reporting views.

### Candidate future summaries
- sponsors needing attention
- recent cultivation outcomes
- recent funding-interest signals
- no-touch-in-X-days list
- demand-linked sponsor activity summary

### Important design note
These should remain practical and compact, not dashboard theater.

## 9. Template discipline refits

### Why
As workflow features grow, templates are at risk of becoming cluttered.

### Ongoing refit needs
- avoid duplicate action rendering
- keep one clear action zone per row
- avoid cue overgrowth
- preserve page readability
- keep sponsor and demand page roles distinct

### Likely slice impact
- Sponsors templates
- view shaping and page layout patterns

## 10. Documentation maintenance refit

### Why
Sponsors CRM is now large enough that its documentation can drift.

### Ongoing documentation tasks
- keep glossary current
- update workflow guide when new actions are added
- update boundary map when seams expand
- refresh acceptance criteria after major changes
- note any future operator queue model clearly

## Not recommended at present

The following are not recommended for near-term development:
- automated sponsor temperature engines
- predictive donor scoring
- silent posture mutation
- enterprise-style funnel dashboards
- abstract “engagement intelligence” layers

These would conflict with VCDB’s scale, philosophy, and present needs.

## Suggested development order for future work

1. sponsor dossier refinement
2. human needs-attention queue
3. standard outcome categories
4. sponsor next-touch summary
5. stewardship support
6. relationship stage if still needed
7. compact reporting summaries

This order keeps the work practical, operator-centered, and aligned with
the present MVP.
