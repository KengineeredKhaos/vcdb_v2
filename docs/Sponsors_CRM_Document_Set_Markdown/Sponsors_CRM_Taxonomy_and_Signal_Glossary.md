# Sponsors CRM — Taxonomy and Signal Glossary

## Purpose

This glossary explains the main Sponsors CRM terms, cues, and signals in
plain language.

It is not a schema specification. It is a working reference for
developers and operators.

## CRM factors

CRM factors are sponsor-local relationship indicators captured in the
Sponsors slice.

They help describe:
- mission fit
- preferred support style
- relationship history
- potential friction or caution
- restrictions or sensitivities

They are used for:
- advisory matching
- sponsor dossier context
- operator review

They are **not** the same thing as governance policy and should not be
treated as absolute truth.

## CRM posture snapshot

A CRM posture snapshot is the stored representation of sponsor CRM
factors at a point in time.

Current storage uses Sponsor History with:
- `section = "sponsor:crm_factors:v1"`

This allows:
- read models
- index/projection support
- practical historical persistence

## Profile note hints

Profile note hints are operator-friendly relationship notes that help
staff approach a sponsor wisely.

Examples:
- warm history with veteran-focused asks
- prefers concise requests
- best approached by email
- may need board review
- interest appears stronger for local efforts

These hints should remain useful and readable.

## Opportunity matching

Opportunity matching is an advisory process that compares a funding
demand with sponsor CRM context.

It produces:
- reasons
- cautions
- note hints
- suggested next action

It does **not** produce authoritative truth.

## Reasons

Reasons are positive or explanatory cues for why a sponsor may be worth
considering for a given demand.

Examples:
- mission alignment
- support style alignment
- prior success
- geographic fit
- population fit

Reasons should help the operator understand why a sponsor appears in the
list.

## Cautions

Cautions are risk or friction cues.

Examples:
- prior decline
- likely board review friction
- mismatch in likely support style
- potential restriction tension

Cautions are not automatic blockers. They are prompts for judgment.

## Note hints

Note hints are human-readable context clues shown alongside a match.

Their purpose is to make the match more actionable.

Examples:
- may respond best to concise local-veteran framing
- previous interaction suggests timing matters
- likely to ask for additional detail before deciding

## Cultivation task

A cultivation task is a Calendar task created for sponsor relationship
work.

Typical purpose:
- initial outreach
- check-in
- information gathering
- follow-up touch
- ask preparation

Cultivation tasks may optionally carry `funding_demand_ulid` so the work
is linked to a specific funding need.

## Cultivation outcome

A cultivation outcome is the result of completed cultivation work as
captured by Calendar and returned to Sponsors.

Outcome rows are signal-based, not fully interpretive.

## Cultivation signals

### `follow_up_recommended`
Meaning:
The completed touch suggests another contact or action is likely useful.

Operator interpretation:
Consider creating a follow-up task or reviewing the sponsor dossier.

### `off_cadence_follow_up_signal`
Meaning:
Something about the interaction suggests the usual or expected timing may
need to be adjusted.

Operator interpretation:
A prompt may need to happen sooner, differently, or outside normal
routine.

### `funding_interest_signal`
Meaning:
The cultivation outcome suggests possible sponsor interest in the demand
or related support.

Operator interpretation:
Review the note and decide whether to schedule a more specific follow-up.

## Follow-up states on demand pages

The current demand-centered view uses a simple, readable follow-up state.

### `follow_up_scheduled`
Meaning:
There is already an open/planned cultivation task for this sponsor and
demand.

### `follow_up_pending_review`
Meaning:
The latest completed outcome for this sponsor and demand surfaced a cue
that suggests follow-up may be needed, but no open/planned follow-up is
yet present.

### `none`
Meaning:
There is no current follow-up cue surfaced by the simplified state
derivation.

## Operator cues

Operator cues are lightweight labels shown on relevant pages to help a
human decide what to do next.

Examples:
- Follow-up recommended
- Off-cadence follow-up
- Funding interest surfaced
- Review CRM posture

They should remain:
- readable
- explicit
- modest in number
- non-automated

## Sponsor “temperature”

VCDB does not use an automated sponsor-temperature field at present.

In practice, sponsor temperature should be inferred by a person from:
- recent activity
- recent outcomes
- pending follow-up
- relationship notes
- local knowledge

Any future attempt to formalize temperature should remain operator-set or
queue-based, not hidden or automatic.

## Relationship knowledge promotion

Promotion means taking a useful cultivation outcome note and preserving
it as sponsor relationship knowledge so it remains visible after the
individual task fades from view.

Good candidates for promotion:
- communication preferences
- timing sensitivities
- likely restrictions or comfort zones
- durable relationship intelligence

## Suggested future glossary additions

The following terms may be added later if they become canon:
- relationship stage
- next-touch summary
- stewardship status
- contact preference profile
- relationship owner
- queue priority
