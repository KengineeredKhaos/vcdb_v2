Absolutely. Here is the **Customer model refit spec in plain English**, based on the current models file and the decisions we’ve pinned so far.

---

# Customer model refit spec v0.1

## Design posture

The current file is not trash. It has a decent skeleton:

- `Customer` = shallow customer card / workflow shell

- `CustomerEligibility` = eligibility facet

- `CustomerProfile` = current assessment session anchor

- `CustomerProfileRating` = per-factor rating rows

- `CustomerHistory` = append-only customer-centered timeline

That structure is worth **keeping**.

What needs refit is the meaning of several fields, especially:

- needs progression

- assessment completeness

- tier unlock truth

- rating semantics

The main correction is:

**replace vague/binary “needs complete” thinking with separate truths for eligibility, assessed tiers, unlocked tiers, and full assessment state.**

---

# 1) `Customer` table

## Keep

These fields still make sense:

- `entity_ulid`

- `status`

- `intake_step`

- `intake_completed_at_iso`

- `watchlist`

- `tier1_min`

- `tier2_min`

- `tier3_min`

- `flag_tier1_immediate`

## Re-interpret

### `status`

Keep it as the broad customer lifecycle flag:

- `intake`

- `active`

- `suspended`

- `archived`

That is still useful.

### `intake_step`

Keep it as **wizard/navigation state**, not deep business truth.

It answers:

- where the operator is in the intake flow

It does **not** answer:

- whether the customer is eligible

- whether a tier is unlocked

- whether the full assessment is complete

So it stays, but it gets demoted to workflow-navigation truth.

## Deprecate / replace

### `needs_state`

Current values:

- `not_started`

- `in_progress`

- `complete`

- `skipped`

This is too blunt for the model you now want.

It collapses several truths into one muddy field:

- has assessment started?

- is Tier 1 done?

- is full assessment done?

- was some portion intentionally skipped?

My recommendation:

**deprecate `needs_state`** after routes/services are moved to clearer booleans.

Do not build new logic on it.

## Add

These booleans belong on `Customer` because they are shallow, operator-useful, customer-card truths.

### Eligibility / service readiness

- `eligibility_complete`

- `entity_package_incomplete`

Notes:

- `eligibility_complete` is Customer-owned truth

- `entity_package_incomplete` is Entity-owned advisory truth mirrored through seam use, not computed by Customer

### Tier assessment truth

- `tier1_assessed`

- `tier2_assessed`

- `tier3_assessed`

These answer:

- has this tier’s factor block been touched sufficiently

### Tier unlock truth

- `tier1_unlocked`

- `tier2_unlocked`

- `tier3_unlocked`

These answer:

- is referral/service work for this tier allowed

These should be derived/cached by service logic, not manually typed.

### Broader assessment truth

- `assessment_complete`

Optional later:

- `reassessment_due`

- `reassessment_complete`

I would **not** add reassessment booleans yet unless current routes/services truly need them. Governance cadence can come later.

## Recommended `Customer` meaning after refit

`Customer` becomes the shallow operational card that answers:

- who is this customer (`entity_ulid`, `name_card` via seam)

- where are we in intake (`intake_step`)

- broad lifecycle status (`status`)

- is eligibility resolved (`eligibility_complete`)

- which assessment tiers are actually assessed

- which service tiers are unlocked

- is there an urgent Tier 1 issue (`flag_tier1_immediate`)

- is the Entity package incomplete (`entity_package_incomplete`, advisory only)

That is a strong, honest card.

---

# 2) `CustomerEligibility` table

## Keep

These fields still belong here:

- `entity_ulid`

- `veteran_status`

- `veteran_method`

- `branch`

- `era`

- `homeless_status`

- `approved_by_ulid`

- `approved_at_iso`

This remains the right place for policy-relevant customer qualifiers.

## Keep constraints

The current approval/method constraints are good and should stay.

They correctly enforce:

- method required when verified

- approval required for `other`

- approver/timestamp parity

## Do not add

Do **not** start putting needs/profile facts here.

This table should stay tight:

- eligibility truth

- qualifier truth

- approval truth

That is all.

## Derived meaning

Service logic should derive:

- `eligibility_complete`

from this facet, rather than making operators set that by hand.

---

# 3) `CustomerProfile` table

## Keep

These fields still make sense:

- `entity_ulid`

- `assessment_version`

- `last_assessed_at_iso`

- `last_assessed_by_ulid`

## Purpose after refit

This table should remain the anchor for the **current needs assessment session/version**.

That is the right role for it.

## Add?

Only if truly useful right now:

- `assessment_started_at_iso`

- `assessment_started_by_ulid`

These are optional. I would not add them unless the routes/services genuinely need them.

Current baseline can survive without them.

## Do not overload

Do not make `CustomerProfile` the place where you store shallow card booleans like:

- `tier1_assessed`

- `tier1_unlocked`

- `assessment_complete`

Those belong on `Customer` as cached operational truth.

Keep `CustomerProfile` as the version/session anchor.

---

# 4) `CustomerProfileRating` table

This is where the biggest semantic refit belongs.

## Keep

These are right:

- `entity_ulid`

- `assessment_version`

- `category_key`

The composite PK is good.

## Change

### `rating_value`

Current:

- `String(16)`

- default `"na"`

- enum `('immediate','marginal','sufficient','unknown','na')`

This is the main problem area.

### Problem

Right now `"na"` is trying to mean too many things:

- untouched/unassessed

- not applicable

That makes the data ambiguous.

## Add

### `is_assessed: bool`

Default:

- `False`

Meaning:

- `False` = untouched, not yet evaluated

- `True` = operator has assessed/touched this factor

This is the cleanest fix.

## Refine `rating_value`

Keep it semantic string data, but make the values honest.

Recommended allowed values:

- `immediate`

- `marginal`

- `sufficient`

- `unknown`

- `not_applicable`

And remove overloaded `"na"`.

### Default

Two safe options:

#### Option A, cleaner

- `rating_value` nullable

- `is_assessed=False` means untouched

#### Option B, explicit text

- `rating_value='unassessed'`

- `is_assessed=False` still exists

I prefer **Option A**:

- bool carries the touched truth

- nullable rating carries result only after assessment

That is the cleanest model.

## Tier assessment rule

A factor counts as assessed when:

- `is_assessed=True`

A tier counts as assessed when:

- every factor in that tier has `is_assessed=True`

That matches what you said:  
a numeric value, `unknown`, or `not_applicable` all count as touched enough to move on.

## Tier min rollup rule

Map only these to numeric rank:

- `immediate` → `1`

- `marginal` → `2`

- `sufficient` → `3`

Ignore for min rollups:

- `unknown`

- `not_applicable`

- untouched rows

If no numeric values exist in a tier:

- `tierN_min = NULL`

That is honest.

## What not to do

Do not switch raw DB values to numeric codes unless you truly want that everywhere.

Keeping semantic strings in the DB is clearer and easier to inspect.

---

# 5) `CustomerHistory` table

## Keep

The overall structure is good:

- append-only

- customer-centered

- source slice recorded

- cached envelope fields

- admin tag support

- actor stamp

- structured blob

That should remain.

## Keep these fields

- `entity_ulid`

- `kind`

- `happened_at_iso`

- `source_slice`

- `source_ref_ulid`

- `schema_name`

- `schema_version`

- `title`

- `summary`

- `severity`

- `public_tags_csv`

- `has_admin_tags`

- `admin_tags_csv`

- `created_by_actor_ulid`

- `data_json`

## Clarify meaning

This table is not just “stuff Customers wrote.”

It is the **customer-centered timeline**, potentially with producers from:

- Customers

- Resources

- Logistics

That matches what you laid out.

## Keep admin tags

I would keep:

- `severity`

- `public_tags_csv`

- `admin_tags_csv`

- `has_admin_tags`

Your fraud/documentation reasoning is sound.

These should stay narrow and disciplined, but they are justified.

## Do not expand casually

Do not turn CustomerHistory into a junk drawer of unbounded slice-private detail.

It should stay:

- reference-oriented

- summarized

- customer-centered

- no PII

---

# 6) Taxonomy refit

## Keep the category groups

These are good and already match what you pinned:

### Tier 1

- food

- hygiene

- health

- housing

- clothing

### Tier 2

- income

- employment

- transportation

- education

### Tier 3

- family

- peergroup

- tech

## Refine rating values

Current taxonomy uses:

- `immediate`

- `marginal`

- `sufficient`

- `unknown`

- `na`

Recommended:

- `immediate`

- `marginal`

- `sufficient`

- `unknown`

- `not_applicable`

And add separate `is_assessed` on rows.

## UI scale

Your UI can still show:

- `1 = immediate`

- `2 = marginal`

- `3 = sufficient`

- `unknown`

- `n/a`

That is fine.

I would just keep the **stored DB values semantic**, not numeric labels.

---

# 7) Derived truths the services should own

These should be computed in services and cached on `Customer`:

## Eligibility

- `eligibility_complete`

## Tier completeness

- `tier1_assessed`

- `tier2_assessed`

- `tier3_assessed`

## Tier unlocks

- `tier1_unlocked`

- `tier2_unlocked`

- `tier3_unlocked`

## Assessment posture

- `assessment_complete`

## Urgency

- `flag_tier1_immediate`

## Rollups

- `tier1_min`

- `tier2_min`

- `tier3_min`

That gives routes/templates/contracts a small, honest, ready-to-eat card.

---

# 8) Fields to avoid adding

Do **not** add any of this to Customer:

- phone

- email

- street address

- mailing address

- duplicated Entity completeness details

- giant serialized profile blobs

- service-readiness booleans for every individual downstream program

Keep Customer focused on customer-domain truth.

---

# 9) Minimal migration posture

If you want the least painful path, I would stage it like this:

## First pass

- add new booleans to `Customer`

- add `is_assessed` to `CustomerProfileRating`

- expand/rename rating enum semantics

- stop defaulting raw ratings to overloaded `"na"`

## Second pass

- update service recompute logic

- stop relying on `needs_state`

- backfill booleans from current rows where possible

## Third pass

- remove or retire `needs_state` once routes/contracts/templates stop using it

That keeps the surgery controlled.

---

# 10) My recommended pin

This is the sentence I’d pin for the refit:

**Customer remains a shallow operational card plus customer-domain facets. Eligibility, assessed tiers, unlocked tiers, and assessment completion are separate truths and should not be collapsed into a single needs-state flag. Needs-factor rows must separate “assessed/touched” from the assessment result. Customer continues to depend on Entity only for `entity_ulid`, `name_card`, and the advisory `entity_package_incomplete` flag.**

---

# What I think the immediate next design sheet should be

Now that the model refit direction is defined, the next clean sheet is:

**Customer workflow/state model**

Specifically:

- what `intake_step` values remain

- what `status` really means

- when `eligibility_complete` flips true

- when each `tierN_assessed` flips true

- when each `tierN_unlocked` flips true

- what `assessment_complete` means

- whether Tier 2/3 unlocks require only their own assessment, or also resolution of lower-tier immediate conditions

That is the next place where ambiguity still lives.

---

Exactly. The workflow/state sheet is where the hidden mess usually reveals itself.

If we do it cleanly, it will show you whether the current slice is confusing:

- wizard navigation

- service readiness

- customer lifecycle

- assessment progress

- follow-up debt

Those should be separate truths.

Here is the sheet.

# Customer workflow/state model v0.1

## 1. Four separate state lanes

Customer should not try to answer everything with one field.

There are four different lanes:

### A. Intake step

This is just operator workflow/navigation.

It answers:  
**Where is the operator in the Customer workflow right now?**

Examples:

- `eligibility`

- `tier1`

- `tier2`

- `tier3`

- `review`

- `complete`

This is not business truth. It is UI/workflow truth.

### B. Customer status

This is broad lifecycle truth.

It answers:  
**What is the standing of this customer record in the Customer slice?**

Recommended:

- `intake`

- `active`

- `inactive`

- `archived`

I would avoid overloading this with fine-grained assessment meaning.

### C. Service-readiness truth

This is the heart of the slice.

It answers:  
**What level of service/referral is responsibly available right now?**

This is where the important booleans live:

- `eligibility_complete`

- `tier1_assessed`

- `tier2_assessed`

- `tier3_assessed`

- `tier1_unlocked`

- `tier2_unlocked`

- `tier3_unlocked`

- `assessment_complete`

- `flag_tier1_immediate`

### D. Follow-up / incompleteness truth

This is operational debt.

It answers:  
**What still needs attention, without pretending missing facts exist?**

Examples:

- `entity_package_incomplete`

- `followup_needed`

- `deferred_reason_code`

- `last_reviewed_at`

- `last_reviewed_by_actor_ulid`

This is where “not done yet” should live, instead of muddying customer facts.

---

## 2. Meaning of each major field

## `intake_step`

Recommended meaning:  
the current operator-facing stage of the Customer workflow.

Recommended values:

- `eligibility`

- `tier1`

- `tier2`

- `tier3`

- `review`

- `complete`

Notes:

- it may move backward

- it may be corrected

- it is not the same thing as customer status

- it is not proof that a tier is actually assessed

So if a route moves `intake_step`, that should not automatically imply business truth changed.

## `status`

Recommended meaning:  
broad Customer lifecycle standing.

Recommended values:

- `intake` = still being established

- `active` = eligible and being serviced or service-ready

- `inactive` = not currently active in service workflow but retained

- `archived` = no longer an active working record

I would avoid `suspended` unless you already have a real policy meaning for it.

## `eligibility_complete`

Recommended meaning:  
the eligibility facet is resolved enough for Customer entry/service consideration.

This flips true when:

- veteran status is resolved as required by policy

- veteran method is resolved when required

- approval metadata exists when required

This is the first bar to entry.

## `tierN_assessed`

Recommended meaning:  
every factor in that tier has been touched by the operator.

This flips true when:

- every rating row in that tier has `is_assessed=True`

Not when all answers are favorable.  
Not when all answers are numeric.  
Just when that tier has actually been evaluated.

## `tierN_unlocked`

Recommended meaning:  
service/referral actions for that needs tier are allowed.

This is not identical to `tierN_assessed`.

Recommended logic:

- `tier1_unlocked = eligibility_complete and tier1_assessed`

- `tier2_unlocked = eligibility_complete and tier2_assessed`

- `tier3_unlocked = eligibility_complete and tier3_assessed`

That is the simplest honest baseline.

Later, Governance can make this stricter if needed.

## `assessment_complete`

Recommended meaning:  
all assessment tiers currently in scope have been assessed.

Baseline simple definition:

- `assessment_complete = tier1_assessed and tier2_assessed and tier3_assessed`

Later you could adjust scope, but this is a solid starting truth.

## `flag_tier1_immediate`

Recommended meaning:  
at least one Tier 1 factor is rated `immediate`.

This is urgency truth, not completeness truth.

It affects:

- cadence

- operator attention

- maybe review priority

It should not be confused with whether Tier 1 is unlocked.

## `entity_package_incomplete`

Recommended meaning:  
advisory flag from Entity that the broader identity record package is incomplete.

Rules:

- advisory only

- does not block Customer workflow by itself

- owned by Entity

- visible in Customer

---

## 3. Recommended state transitions

Here is the basic progression.

## Intake creation

When a Customer is first created from Entity handoff:

Set:

- `status = intake`

- `intake_step = eligibility`

- `eligibility_complete = False`

- `tier1_assessed = False`

- `tier2_assessed = False`

- `tier3_assessed = False`

- `tier1_unlocked = False`

- `tier2_unlocked = False`

- `tier3_unlocked = False`

- `assessment_complete = False`

- `flag_tier1_immediate = False`

This gives a clean starting card.

## After eligibility resolved

If eligibility is complete:

Set:

- `eligibility_complete = True`

Do not automatically set:

- `status = active`

until you decide whether active begins at eligibility or at first usable service level.

My recommendation:

- `status` may stay `intake` until Tier 1 is assessed

- then flip to `active` once the record is actually service-ready

That better reflects operational reality.

## After Tier 1 assessed

When all Tier 1 rows are touched:

Set:

- `tier1_assessed = True`

- compute `tier1_min`

- compute `flag_tier1_immediate`

- recompute `tier1_unlocked`

If eligibility is complete, this is the first meaningful service threshold.

Recommended outcome:

- `tier1_unlocked = True`

- `status = active`

Because now you are “done enough to address immediate quality-of-life needs.”

## After Tier 2 assessed

Set:

- `tier2_assessed = True`

- compute `tier2_min`

- recompute `tier2_unlocked`

This expands referral/service scope.

## After Tier 3 assessed

Set:

- `tier3_assessed = True`

- compute `tier3_min`

- recompute `tier3_unlocked`

## After all tiers assessed

Set:

- `assessment_complete = True`

- `intake_step = complete`

That is the cleanest place to say intake workflow is done.

---

## 4. Backward movement and corrections

This is where many systems get sloppy.

Not every backward move is bad. Some are honest corrections.

## `intake_step`

May move backward freely as operator workflow truth.

Examples:

- review back to tier2

- tier3 back to eligibility for correction

That is fine.

## `status`

Should move more cautiously.

Examples:

- `active` back to `intake` only if foundational truth was truly undone

- `active` to `inactive` should require a real operational reason

- `archived` should be rare and deliberate

## readiness booleans

Should always be recomputed from facts, not manually toggled.

That is the big rule.

Do not let operators hand-edit:

- `tier1_unlocked`

- `assessment_complete`

- `flag_tier1_immediate`

Those should be service-derived.

---

## 5. Deferred / incomplete truth

You raised this earlier, and this is where it belongs.

I would not use `skipped` as a giant catch-all state anymore.

Instead, separate:

- workflow moved forward

- some area still needs follow-up

So if Tier 3 is intentionally deferred, that does not mean the customer is fake or broken. It means:

- Tier 1 and Tier 2 may still support real action

- `assessment_complete = False`

- follow-up truth records what remains

So I would retire the old blunt `needs_state` concept and replace it with:

- assessed booleans

- unlock booleans

- assessment_complete

- explicit follow-up/defer metadata where needed

That is much more honest.

---

## 6. Recommended status rule

This is the one place where a clean choice will simplify a lot.

I recommend:

- `status = intake` until `eligibility_complete and tier1_assessed`

- `status = active` once Tier 1 service readiness exists

- `status = inactive` when not currently active in service workflow

- `status = archived` when intentionally removed from active operations

Why this is good:  
it aligns the status flip with the first real service-readiness threshold, not just data entry.

---

## 7. The big problems this sheet will expose in current code

This sheet should help you spot these common design bugs immediately:

### Problem 1

Using `intake_step` as if it were service truth.

It is not. It is just where the operator is in the flow.

### Problem 2

Using one field like `needs_state` to mean:

- started

- in progress

- complete

- deferred

- service-ready

That is too much for one field.

### Problem 3

Treating urgency and completeness as the same thing.

They are not.

- `flag_tier1_immediate` = urgency

- `tier1_assessed` = completeness

- `tier1_unlocked` = readiness

### Problem 4

Blocking service because Entity package polish is incomplete.

That violates the boundary you just defined.

### Problem 5

Letting operators manually set derived truths.

Derived truths should be recomputed from facts.

---

## 8. My recommended pin

This is the wording I would pin:

**Customer workflow/state must distinguish operator workflow step, broad customer lifecycle status, staged service-readiness truth, and follow-up/incompleteness truth. `intake_step` is navigation state only. Service readiness is staged through `eligibility_complete`, `tierN_assessed`, `tierN_unlocked`, and `assessment_complete`. `flag_tier1_immediate` expresses urgency, not completeness. Entity package incompleteness is an advisory signal and must not block Customer workflow by itself.**

---

## 9. Best next wicket

Now that this is on paper, the next thing to settle is the **Customer history envelope and event discipline**, because once states are separated, we can say exactly:

- which state changes deserve history

- which deserve ledger events

- which are just harmless workflow navigation

- which are noops

That will show you where the existing routes/services are emitting too much, too little, or at the wrong layer.

---

On Status: 
This was originally supposed to be only a quick and dirty indicator that poses the simple question of: 
"Have we dealt with this person before and roughly where are we with them?"

Intake answers "We have but we need more info before we can help."
Active answers "We have, we have enough data to issue, may need follow-up."
Inactive answers "This guy hasn't been around for 2 years or more, reassess."
Archived answers "This guy is supposed to be dead and there's a valid reason."

That somehow mutated into state machine values that I don't even understand. Obviously, we're not going to disappear data and regress from active to intake and we're certainly not in the business of resurrecting people from the grave to issue a pair of boot to them once a year. 

State Machine and regression is some cool shit your system made up to hang on "status". Have less than a clue what to do with that. And perhaps more importantly, why we're chasing a hallucination drop a rabbit hole to begin with?

---

You’re right. I overfit **status** into a formal state machine when your intent was a **coarse operator shorthand**. That was the wrong move.

`status` should stay dumb and useful:

- **intake** = we know this person, but not enough yet to help responsibly

- **active** = we know enough to issue/service; follow-up may still exist

- **inactive** = stale record; reassess before acting

- **archived** = closed off for a real reason, not normal operations

That is not a rich workflow engine. It is a **quick posture flag** for the operator.

The real mistake was trying to make `status` carry jobs that belong somewhere else. Those jobs should live in separate fields:

- `intake_step` = where the operator is in the workflow

- `eligibility_complete`

- `tier1_assessed`, `tier2_assessed`, `tier3_assessed`

- `tier1_unlocked`, `tier2_unlocked`, `tier3_unlocked`

- `assessment_complete`

- freshness / reassessment flags later

Those fields answer the real operational questions. `status` just answers, “roughly where are we with this person?”

So I would correct the model like this:

`status` is **not** the state machine.  
`status` is a **coarse record posture**.

The only transitions that really make sense are:

- `intake -> active`

- `active -> inactive`

- `inactive -> active`

- non-archived -> `archived` by explicit reason

And importantly:

- **no active -> intake**

- **no archived -> active**

- `intake_step` can move around without changing `status`

That keeps `status` aligned with your original intent and stops us from hanging logic on the wrong peg.

So the rabbit hole was real, but the fix is simple:  
we stop treating `status` as the brain of the slice.

The next sheet should use this rule and focus on the fields that actually drive work: **eligibility, tier assessment, unlocks, and history/event discipline.**

---

Befgore we dig into Customer History envelop, the orginal objective was to create an blank form for uniformity in essential, pertinent data, DATE, ULID's, name-card, who is the source slice of the activity or support provided to the customer (Customers, Resources, Logistics) and a text blob or narrative. 

Logistics transactions are logged only in Logistics. Logistics owns that data and uses it many ways. Issuance to a customer needs to tracked by customer so a transaction synopsis/narrative/free-form list of the Logistics activity with that customer is prepared using that JSON envelop and sent to CustomerHistory for storage and recall.

Same thing with a Resource Referrral. There was some sort of outcome from that referral and that data needs a home in CustomerHistory so we can see it. The JSON schema is simply a way for each slice to know the envelop CustomerHistory expects to be storing and Customer services expects to be searching within for particular fields/indicators. 

Each concerned slice has the same CustomerHistory JSON schema on file within their slice and is expected to send data to CustomerHistory using that format. Just enough structure to be searchable without a matrix of data tables and fields

---

Yes — that makes CustomerHistory much clearer, and it is a good design.

What you’re describing is **not** a second copy of Logistics or Resources data.  
It is a **customer-centered synopsis layer**.

That means:

- the **owning slice keeps the real operational record**

- CustomerHistory keeps the **customer-facing summary/reference**

- enough structure exists to search and filter it

- the narrative/blob carries the human-meaningful context

- no one is forced into a huge cross-slice relational tangle

That is a solid model.

## So CustomerHistory becomes

A **customer timeline index** with:

- when something happened

- which customer it concerns

- which slice produced it

- which source record it refers to

- who drove or recorded it

- a short title/summary

- a structured blob for searchable detail

- optional tags/severity/admin markers

Not the full source record.  
Not the source-of-truth.  
Not a shadow database.

## That means the hard rule should be

**CustomerHistory stores synopsis, reference, and searchable customer-centered narrative.  
The owning slice stores the actual transaction/business record.**

So for example:

### Logistics

- Logistics owns issuance facts, quantities, SKU logic, restrictions, inventory impact

- CustomerHistory stores:
  
  - issuance happened
  
  - rough what/why/outcome
  
  - source ref back to Logistics
  
  - maybe a short item synopsis in the blob

### Resources

- Resources owns referral workflow, provider details, acceptance/decline, outcome mechanics

- CustomerHistory stores:
  
  - referral made
  
  - referral outcome/update
  
  - short operational summary
  
  - source ref back to Resources

That is exactly the right split.

---

# What I would pin about the envelope

I would define the envelope as two layers:

## A. First-class indexed fields on the CustomerHistory row

These are for fast filtering, sorting, and broad searching.

Recommended essentials:

- `entity_ulid`

- `happened_at_iso`

- `source_slice`

- `source_ref_ulid`

- `kind`

- `created_by_actor_ulid`

- `title`

- `summary`

- `severity`

- `public_tags_csv`

- `has_admin_tags`

- `admin_tags_csv`

- `schema_name`

- `schema_version`

- `data_json`

That is enough structure without overbuilding.

## B. The JSON blob

This is where each producing slice puts the **synopsis payload** in a common expected shape.

That is where you can carry:

- short narrative

- outcome notes

- simple item/service lists

- reason codes

- status hints

- follow-up indicators

Structured enough to search.  
Loose enough to avoid a matrix of tables.

That matches your stated objective very well.

---

# One refinement I strongly recommend

You said:

> Each concerned slice has the same CustomerHistory JSON schema on file within their slice

Functionally, yes, they need to know the shape.  
But I would not make them each own their own drifting copy.

I would strongly recommend:

**one canonical CustomerHistory schema definition**  
and each slice maps to it locally.

In other words:

- one schema source of truth

- many producer mappers/adapters

That prevents quiet drift where:

- Logistics thinks `outcome_status` means one thing

- Resources spells it differently

- Customers expects a different field name

So the better rule is:

**shared schema, slice-local mapper**

That fits your architecture better than duplicated schema copies.

---

# One more important correction

I would **not store `name_card` in CustomerHistory rows**.

Why:

- `name_card` is a read seam

- it is minimal PII

- it may improve or change over time

- `entity_ulid` already identifies the customer

So for history storage, I would keep:

- `entity_ulid`

And at render time:

- resolve the current `name_card`

That keeps the stored history leaner and avoids unnecessary duplication of even minimal PII.

So your blank form should probably store:

- date/time

- entity ULID

- source ref ULID

- actor ULID

- source slice

- kind/title/summary

- JSON narrative blob

And the UI can hydrate:

- `name_card`

on read.

---

# The resulting philosophy

This gives CustomerHistory a very crisp job:

**CustomerHistory is the customer-facing memory of what was done with or for the customer, not the place where source slices surrender ownership of their real records.**

That is a good fit for your app.

---

# What I would write as the pinned rule

**CustomerHistory is a customer-centered synopsis and recall surface. Source slices such as Customers, Resources, and Logistics retain ownership of their full operational records. CustomerHistory stores a normalized envelope with indexed reference fields plus a structured JSON synopsis/narrative payload that is searchable but intentionally lighter than the source record. The history row identifies the producing slice and source record so operators can trace back to the owning workflow. `name_card` should be resolved on read from `entity_ulid`, not duplicated into stored history rows.**

That leaves us ready for the next hard question:

**what exact fields belong in the canonical CustomerHistory JSON payload, and which belong only in the indexed row columns?**

Good copy, no name_cards that could go stale and centralized storage for the CustomerHistory JSON schema...   Perhaps in Governance as, technically it is a system-wide "policy" that everyone use the same form, it's just a "fixed policy" .  

I’d keep the **idea** in Governance, but not the **runtime schema file** itself.

Why:

- **Governance policy** should answer things like:
  
  - which slices are allowed/expected to write CustomerHistory
  
  - retention expectations
  
  - maybe allowed `severity` / tag taxonomy later

- the **CustomerHistory schema** is really a **shared technical contract**
  
  - field names
  
  - payload shape
  
  - versioning rules
  
  - what producers must send

If we put every cross-slice technical contract into Governance just because it is system-wide, Governance turns into a junk drawer.

So my recommendation is:

## Best split

### Governance

Owns the policy statement:

- CustomerHistory is the canonical customer-centered synopsis surface

- approved producer slices

- no PII rule

- retention posture

- maybe taxonomy rules later

### Shared technical layer

Owns the actual canonical schema:

- one JSON Schema file

- one versioned DTO/contract definition

- slice-local mappers/adapters feed it

That keeps the boundaries clean:

- Governance = business rule / policy

- shared schema = technical envelope contract

- slices = produce their own synopsis payloads into that contract

## Best home

Given your canon, I would put the canonical schema in a shared technical location, not in Governance.

Something like:

- `app/lib/schemas/customer_history_entry_v1.json`  
  or

- `app/lib/schema/customer_history_entry_v1.json`

And pair it with a small shared helper or DTO definition.

Then each slice has its own mapper:

- Customers → customer history mapper

- Resources → customer history mapper

- Logistics → customer history mapper

## Why this is better

Because this thing is closer to:

- `entity_v2`

- `customers_v2`

- shared DTO/schema canon

than it is to:

- funding controls

- issuance policy

- governance authority

It is a **system contract**, not a **governance decision**.

## The sentence I’d pin

**CustomerHistory envelope shape is a shared technical contract, not a Governance policy file. Governance may define the policy that CustomerHistory exists and who may write to it, but the canonical JSON schema should live in a shared technical schema location with slice-local mappers feeding it.**

That will save you from making Governance the bucket for every app-wide fixed rule.

The next useful move is to draft the actual **canonical field list** for:

- row columns

- JSON payload fields

- required vs optional fields

- producer invariants

---

We don't need a policy on this, it's an immutable mechanics Dev decision, not a Board decision. 

app/lib/history_blob/<slice>/ is the new home for history blob JSON schemata stored by slice. 

---

Good. That is a cleaner call.

I agree with the principle:

**CustomerHistory blob schema is a mechanics/contract decision, not a Governance decision.**

And your chosen home is workable:

`app/lib/history_blob/<slice>/`

That keeps it:

- outside Governance

- outside any one owning slice

- clearly technical

- organized by producer slice

The one refinement I’d suggest is this:

## Keep one common base plus slice-specific payloads

If each slice gets its own totally free-form schema under that folder, drift can still sneak in. So I’d think of it as:

- **common envelope contract** shared by all producers

- **slice-specific payload schema** under `app/lib/history_blob/<slice>/`

So conceptually:

- shared row/envelope expectations:
  
  - `kind`
  
  - `happened_at`
  
  - `source_slice`
  
  - `source_ref_ulid`
  
  - `actor_ulid`
  
  - `title`
  
  - `summary`
  
  - `schema_name`
  
  - `schema_version`
  
  - `payload`

- then each slice defines only its own `payload` shape

That gives you consistency without forcing every slice into the same narrative details.

So I’d phrase the rule like this:

**CustomerHistory uses a shared envelope with slice-specific payload schemata. The schemata live in `app/lib/history_blob/<slice>/`. This is a technical contract decision, not a Governance policy artifact.**

That leaves us in a good place to tackle the next concrete question:

**what exactly is the shared envelope, and what belongs only inside per-slice payloads?**

---

"So conceptually:
shared row/envelope expectations:
kind
happened_at
source_slice
source_ref_ulid
actor_ulid
title
summary
schema_name
schema_version
payload

then each slice defines only its own payload shape."

Logistics -> a simple list of SKU's and quantities issued
Resources -> simple narrative blob
Customers -> simple list of eligibility and tier factors for each mutation

Those are the big ones, we can add more as the needs arise.

---

Yes. That is small, honest, and enough to start.

I’d lock it like this.

## Shared CustomerHistory envelope

Every producer sends:

- `kind`

- `happened_at`

- `source_slice`

- `source_ref_ulid`

- `actor_ulid`

- `title`

- `summary`

- `schema_name`

- `schema_version`

- `payload`

That is the universal wrapper.

## Producer payload baselines

### Logistics

`payload` contains a simple issued-items list:

- SKU

- quantity

No inventory mechanics, no full transaction copy.

### Resources

`payload` contains a simple narrative blob.

No need to over-structure it yet.

### Customers

`payload` contains a simple list of the eligibility and tier factors involved in the mutation.

Not the whole assessment every time, just the factors relevant to that change.

That gives you:

- searchable structure

- customer-centered recall

- no shadow ownership of source-slice data

- room to grow only when real needs appear

## One guardrail I would add

For `Customers` payload, I would keep it to:

- factor keys

- old/new rating states if appropriate

- maybe a short reason/note

But not broad freeform personal narrative that starts drifting toward PII-heavy case notes.

## Practical naming suggestion

I’d also make the schema naming boring and explicit, for example:

- `logistics.issue.synopsis.v1`

- `resources.referral.synopsis.v1`

- `customers.assessment.synopsis.v1`

That will make versioning and search less slippery later.

So yes — this is enough to move forward.

The next wicket should be **event and history-write discipline**:  
which Customer actions write CustomerHistory, which only emit ledger events, which do both, and which are just workflow navigation with no history at all.

---

Every CustomerHistory write has a ledger entry so we know who did what when and perhaps more importantly, when something FAILED to happen. That event_bus.emit already has a corresponding domain, operation, actor_ulid, target_ulid and meta dictionary. That should be more than enough for activity tracking and diagnostics if needed.

CustomerHistory-worthy events within Customer slice:

History only, Ledger only or Both

Initial assessment/Annual Reassessment -> both, all eligibility and tier values.

Changes in tier values -> both, only the values changed during that session, one entry per session.

Only successful operations. Ledger is an audit trail with diagnostic implications, not the other way around. Denials, failures and errors will rollback the db in the route anyway, no need to spam the ledger with failures. We only do that for Auth login failures and even then, that is limited by attempt count lock-out.

That's enough to get started and see if/what other circumstances arise.

---

That is a good, disciplined starting rule set.

I’d formalize it like this:

## Customer-slice CustomerHistory write rules, baseline

**Write both CustomerHistory and Ledger for:**

- **Initial assessment / annual reassessment**
  
  - include all eligibility values
  
  - include all tier values

- **Changes in tier values**
  
  - include only the values changed during that session
  
  - one history entry per session

## Do not write CustomerHistory or Ledger for:

- failed operations

- denied operations

- validation errors

- rolled-back route attempts

- ordinary workflow/navigation movement

That keeps both surfaces clean:

- **CustomerHistory** stays customer-significant

- **Ledger** stays an audit trail of successful, durable actions

- failures do not spam the system unless there is a special security reason, like Auth lockout tracking

And I think your “one entry per session” rule is especially good. It prevents the timeline from turning into confetti when an operator adjusts several factors in one sitting.

So the pinned Customer-slice baseline becomes:

**Within Customer slice, CustomerHistory-worthy events are successful initial assessment/reassessment sessions and successful tier-value change sessions. Each such write emits a corresponding Ledger event. Initial/reassessment entries include all eligibility and tier values; change-session entries include only the values changed during that session. Failed, denied, or rolled-back operations do not emit Ledger or CustomerHistory entries in the normal case.**

That is enough to move forward.

The next clean wicket is to do the same sorting for the rest of the customer-centered timeline producers:  
**Resources** and **Logistics**.

---

Oops, add to Customer slice History queues:

Resource Referral -> both, we'll need a JSON schema specifically for this.

Resource Referral Outcome -> both, we can use the same schema for this, the only things that change are the source, title and narrative block.

Now that I think about it, Resource slice really has nothing to do with this and it has it's own history of capabilities and capacities to deal with. Resources doesn't need to have its own CustomerHistory reporting DTO because that input will come from Customer slice anyway.

Logistics does need a DTO because it is sending a synopsis of activity to CustomerHistory so operators need to pull Logistics history for a particular customer without crossing slice boundaries to query Logistics data.

Logistics -> both, needs a JSON schema specifically for this. 

That correction tightens the design nicely.

You’ve now split the customer-centered timeline producers more cleanly:

## Customer slice writes to CustomerHistory for:

- **Initial assessment / annual reassessment** → both

- **Tier-value change session** → both

- **Resource referral** → both

- **Resource referral outcome** → both

And the important refinement is:

**Resource referral history is Customer-owned timeline work, not Resources-owned timeline work.**

That means Resources can keep its own internal history for resource/admin purposes, but it does **not** need its own CustomerHistory reporting DTO just to feed the customer timeline. Customer already owns the referral relationship and can write the customer-facing synopsis itself.

## Logistics writes to CustomerHistory for:

- **Logistics issuance synopsis** → both

And here the opposite is true:

**Logistics does need its own DTO/payload schema**, because the owning operational facts live in Logistics and Customer should not cross boundaries to reconstruct them by querying Logistics internals.

So the producer map now looks like this:

## CustomerHistory producer map, baseline

### Customers

Writes CustomerHistory for:

- assessment / reassessment

- tier-value change sessions

- resource referral

- resource referral outcome

### Logistics

Writes CustomerHistory for:

- logistics support/issuance synopsis for a customer

### Resources

Does **not** need a CustomerHistory producer DTO for customer timeline baseline

- Resources keeps its own slice history for resource-side operations

- Customer-side referral and outcome timeline entries are handled by Customer slice

That is a much cleaner ownership split.

# Schema consequences

You now need only two real baseline payload families for CustomerHistory:

## 1. Customers payload schemas

At least two shapes:

### A. Assessment synopsis

For:

- initial assessment

- annual reassessment

- tier-value change sessions

Payload baseline:

- eligibility values relevant to the session

- tier factor values relevant to the session

- changed factor list for change-only sessions

- optional short note/reason

### B. Referral synopsis

For:

- resource referral

- resource referral outcome

Payload baseline:

- referral target/resource reference as available

- referral purpose / need tier

- status or outcome indicator

- short narrative

And yes, referral + referral outcome can share the same schema if the envelope fields plus title/summary/narrative distinguish the event.

## 2. Logistics payload schema

For:

- customer logistics activity synopsis

Payload baseline:

- item list

- SKU

- quantity

Optionally later:

- support context note

- issuance purpose/category

But do not overbuild it now.

# What this also resolves

This answers a subtle seam question:

- **CustomerHistory is not “who physically writes the row in code matters most”**

- it is **“which slice owns the customer-facing synopsis responsibility for this event”**

For referrals, that owner is Customer.  
For issuance activity synopsis, that owner is Logistics.

That is a good principle.

# Updated pinned rule

I’d phrase it this way:

**CustomerHistory entries for assessments, reassessments, tier-value changes, resource referrals, and referral outcomes are Customer-owned timeline writes and emit corresponding Ledger events. Resources does not need a separate CustomerHistory producer DTO for those customer-facing referral events. Logistics does need a CustomerHistory DTO/schema because it must send a customer-centered synopsis of logistics activity without requiring cross-slice querying of Logistics internals.**

The next useful step is to draft the **actual baseline schema names and payload field lists** for:

- `customers.assessment.synopsis.v1`

- `customers.referral.synopsis.v1`

- `logistics.issue.synopsis.v1`

---

# Baseline CustomerHistory schema set

## 1. Customers assessment synopsis

**Schema name:** `customers.assessment.synopsis.v1`

**Used for:**

- initial assessment

- annual reassessment

- tier-value change session

### Shared envelope

- `kind`

- `happened_at`

- `source_slice = "customers"`

- `source_ref_ulid`

- `actor_ulid`

- `title`

- `summary`

- `schema_name`

- `schema_version`

- `payload`

### Payload

- `session_type`
  
  - `initial`
  
  - `reassessment`
  
  - `change_session`

- `eligibility`
  
  - simple object of current relevant eligibility values

- `changed_factors`
  
  - list of factor change objects

- `tiers_touched`
  
  - list like `["tier1"]`, `["tier1","tier2"]`

- `note`
  
  - optional short narrative

### Factor change object

- `factor_key`

- `old_value`

- `new_value`

### Rules

- initial/reassessment includes all current eligibility + tier values

- change session includes only factors changed in that session

- one entry per session

---

## 2. Customers referral synopsis

**Schema name:** `customers.referral.synopsis.v1`

**Used for:**

- resource referral created

- resource referral outcome recorded

### Shared envelope

- `kind`

- `happened_at`

- `source_slice = "customers"`

- `source_ref_ulid`

- `actor_ulid`

- `title`

- `summary`

- `schema_name`

- `schema_version`

- `payload`

### Payload

- `referral_kind`
  
  - `referral_created`
  
  - `referral_outcome`

- `resource_ulid`
  
  - nullable if not yet assigned

- `resource_name`
  
  - optional display convenience

- `need_tier`
  
  - `tier1|tier2|tier3`

- `need_keys`
  
  - list like `["housing"]`

- `status`
  
  - simple string

- `narrative`
  
  - short freeform text

### Rules

- same schema for creation and outcome

- differences mostly live in:
  
  - `kind`
  
  - `title`
  
  - `summary`
  
  - `payload.referral_kind`
  
  - `payload.status`
  
  - `payload.narrative`

---

## 3. Logistics issue synopsis

**Schema name:** `logistics.issue.synopsis.v1`

**Used for:**

- logistics issuance/support activity for a customer

### Shared envelope

- `kind`

- `happened_at`

- `source_slice = "logistics"`

- `source_ref_ulid`

- `actor_ulid`

- `title`

- `summary`

- `schema_name`

- `schema_version`

- `payload`

### Payload

- `items`
  
  - list of issued-item objects

- `note`
  
  - optional short narrative

### Issued-item object

- `sku`

- `quantity`

### Rules

- synopsis only

- no inventory mechanics

- no shadow copy of Logistics internals

---

# Minimal `kind` values

Keep these boring too.

## Customers

- `assessment.initial`

- `assessment.reassessment`

- `assessment.changed`

- `referral.created`

- `referral.outcome`

## Logistics

- `issuance.recorded`

That is enough for now.

---

# Storage layout

Under your chosen home:

- `app/lib/history_blob/customers/assessment_synopsis_v1.json`

- `app/lib/history_blob/customers/referral_synopsis_v1.json`

- `app/lib/history_blob/logistics/issue_synopsis_v1.json`

Simple and obvious.

---

# What this gives us

This is now enough to:

- refit `CustomerHistory` append services honestly

- define producer mappers

- write validation tests

- sort current Customer routes/services into:
  
  - history-worthy
  
  - ledger-worthy
  
  - neither

The next design sheet should be the **Customer contract surface map**:  
which `customers_v2` functions and DTOs survive, which get cut, and which get rebuilt around these truths.

---

# Customer contract surface map v0.1

The rule stays:

**small, boring, brutally honest**

So `customers_v2` should expose only what downstream slices or routes can trust **today**.

## Keep

These are the contract families Customer really should expose.

### 1. Minimal customer summary

Purpose:

- identify the customer in Customer context

- show rough service posture

- support list/detail screens and downstream reads

Fields should look roughly like:

- `entity_ulid`

- `name_card`

- `status`

- `intake_step`

- `eligibility_complete`

- `tier1_assessed`

- `tier2_assessed`

- `tier3_assessed`

- `tier1_unlocked`

- `tier2_unlocked`

- `tier3_unlocked`

- `assessment_complete`

- `flag_tier1_immediate`

- `entity_package_incomplete`

That is a good honest “customer card” seam.

### 2. Eligibility snapshot

Purpose:

- show Customer-owned eligibility truth

- support issuance/referral decisions

Fields:

- `veteran_status`

- `veteran_method`

- `branch`

- `era`

- `homeless_status`

- `approved_by_ulid`

- `approved_at`

No extra fluff.

### 3. Needs/assessment snapshot

Purpose:

- show staged service-readiness truth

- support referrals and reassessment work

Fields:

- tier mins

- tier assessed bools

- tier unlocked bools

- flag_tier1_immediate

- assessment_complete

- assessment version / assessed at / assessed by

- maybe tier factor rows grouped by tier

### 4. History/timeline reads

Purpose:

- customer-centered recall

- operator review surface

Reads should cover:

- history list/timeline summary

- history detail

- maybe admin-tag filtered inbox later

This remains an important contract family.

---

## Refit

These should survive in spirit, but need to be rebuilt to match the new truth model.

### 1. Dashboard DTO

This is where the biggest cleanup belongs.

It should stop pretending Customer knows broad Entity completeness or extra speculative posture fields.

Refit it into a plain operational summary DTO using the fields above.

### 2. Assessment-related DTOs

Any current DTOs that try to boil everything into “profile complete” or a vague needs state should be replaced with:

- eligibility truth

- tier assessed truth

- tier unlocked truth

- assessment complete truth

### 3. History append/write seam

This should absolutely exist, but it needs to be rebuilt around the envelope decisions we just made:

- shared envelope

- slice-specific payload schema

- one entry per session where applicable

---

## Remove

These are the things I would cut from `customers_v2`.

### 1. Phantom fields

Anything that exists only because it sounded useful once, but is not grounded in current Customer truth.

Examples from the earlier review were fields like:

- speculative watchlist timing

- last-touch style values not clearly owned/proven

- broad “profile complete” style claims

- anything implying Customer depends on full Entity record package

### 2. Dead service references

Any contract function that calls helper/service names that do not exist in the slice today needs to go or be rewritten immediately.

No placeholders. No “we’ll hook that up later.”

### 3. Fake richness

Any DTO that tries to be a mega-view for every future need should be slimmed down or removed.

---

## Defer

These can wait until the real need appears.

### 1. Rich referral analytics views

Not needed for hardening.

### 2. Cross-slice performance/reporting DTOs

Not needed yet.

### 3. Deep Admin-only Customer diagnostics

Build when the admin need is real.

### 4. Reassessment policy detail views

Governance cadence can come later.

---

# Recommended contract families

I’d keep `customers_v2` to something like this in spirit:

## Read seams

- get minimal customer summary

- get eligibility snapshot

- get needs/assessment snapshot

- list history summaries

- get history detail

## Write seams

- append customer history entry

- maybe update assessment/eligibility through contract later, but only if another slice truly needs that

For now, I would keep mutating business workflows mostly slice-local unless you already know another slice must call them.

---

# Important boundary rule

`customers_v2` should not expose:

- Entity contact/address detail

- Governance authority logic

- Logistics internals

- Resource internals

- speculative reporting posture

It should expose only:

- Customer-owned service truth

- customer-centered timeline truth

- minimal operator-useful summary truth

---

# The practical test

For every contract function, ask:

**Does this expose a current proven Customer truth another part of the app can safely depend on?**

If yes:

- keep or refit it

If no:

- remove it

That question should cut a lot of scaffolding fast.

---

# My recommendation for the next pass

The next concrete deliverable should be a **keep / refit / remove / defer table for the actual current `customers_v2.py` symbols**, one by one. That will show exactly where the present contract drift is hiding.

---

Yes. I opened the real `customers_v2.py` again and compared it to the uploaded Customer slice.

The good news is the file is small enough that the drift is obvious.

## Immediate blockers in the current contract

Before the table, these are the three biggest hard truths:

1. **Two read functions call service names that do not exist**
   
   - contract calls `cust_svc.get_dashboard_view(...)`
   
   - actual service is `get_customer_dashboard(...)`
   
   - contract calls `cust_svc.get_eligibility_snapshot(...)`
   
   - actual service is `get_customer_eligibility(...)`

2. **The only write function is a stub**
   
   - `append_history_entry(...)` is `pass`
   
   - but the service layer already has a real `append_history_entry(...)`

3. **Several DTOs describe a Customer that no longer matches your pinned philosophy**
   
   - too much vague dashboard posture
   
   - not enough staged readiness truth
   
   - dead write-result DTOs for flows that are not even present

So here is the symbol-by-symbol pass.

# `customers_v2.py` keep / refit / remove / defer table

| Symbol                      | Disposition                     | Why                                                                                                                                                                                                                                                                                                                                          | Replacement / target                                                                                         |
| --------------------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `_as_contract_error`        | **KEEP**                        | Fine as an internal helper. Small and useful.                                                                                                                                                                                                                                                                                                | Keep, maybe extend only if new normalized errors appear.                                                     |
| `NeedsProfileDTO`           | **REFIT**                       | Current shape is too thin and slightly wrong for your new model. It has veteran/homeless + tier mins, but no `eligibility_complete`, no tier assessed/unlocked truth, no `assessment_complete`, no advisory Entity flag.                                                                                                                     | Rebuild as a real **assessment/service-readiness snapshot DTO**.                                             |
| `CustomerCuesDTO`           | **REFIT**                       | This is the best candidate to survive in spirit because cross-slice gating is real. But current fields are off: `watchlist` and `watchlist_since_utc` are not strong baseline gating truth, while `eligibility_complete` and tier unlocks are missing.                                                                                       | Keep the idea, rebuild as a **minimal decision-ready cues DTO**.                                             |
| `DashboardDTO`              | **REMOVE current shape**        | This is the most drifted object in the file. It expects phantom fields like `flag_reason`, `tier_factors`, `first_seen_utc`, `last_touch_utc`, `last_needs_update_utc`, `last_needs_tier_updated`, and relies on a service view that does not exist. It is too rich, too speculative, and not aligned with “small, boring, brutally honest.” | Replace with a much smaller **CustomerSummaryDTO** or **CustomerStatusDTO** built from real Customer truths. |
| `VerificationResultDTO`     | **REMOVE**                      | Dead scaffolding. There is no `verify_veteran(...)` contract function in this file. This DTO is unused and points toward a write seam you have not chosen to publish.                                                                                                                                                                        | Remove from v2. Add back later only if another slice truly needs that contract write.                        |
| `TierUpdateResultDTO`       | **REMOVE**                      | Same issue. Dead write-result scaffolding. No `update_tier1/2/3` contract functions exist.                                                                                                                                                                                                                                                   | Remove from v2.                                                                                              |
| `WHERE_GET_CUSTOMER_CUES`   | **KEEP**                        | Internal constant, harmless, tied to a real function.                                                                                                                                                                                                                                                                                        | Keep.                                                                                                        |
| `WHERE_GET_DASHBOARD_VIEW`  | **REMOVE or rename with refit** | Tied to an overloaded function shape that should not survive as-is.                                                                                                                                                                                                                                                                          | Replace if you keep a summary read under a new name.                                                         |
| `WHERE_GET_NEEDS_PROFILE`   | **KEEP with refit**             | Still useful if the function survives under a better DTO.                                                                                                                                                                                                                                                                                    | Keep if the function survives.                                                                               |
| `WHERE_VERIFY_VETERAN`      | **REMOVE**                      | No published write function. Dead scaffolding.                                                                                                                                                                                                                                                                                               | Remove.                                                                                                      |
| `WHERE_UPDATE_TIER1`        | **REMOVE**                      | No published write function. Dead scaffolding.                                                                                                                                                                                                                                                                                               | Remove.                                                                                                      |
| `WHERE_UPDATE_TIER2`        | **REMOVE**                      | No published write function. Dead scaffolding.                                                                                                                                                                                                                                                                                               | Remove.                                                                                                      |
| `WHERE_UPDATE_TIER3`        | **REMOVE**                      | No published write function. Dead scaffolding.                                                                                                                                                                                                                                                                                               | Remove.                                                                                                      |
| `get_profile(...)`          | **REMOVE**                      | A stable contract should not carry a permanent 501 tombstone for a thing you no longer want. This is just noise.                                                                                                                                                                                                                             | Delete it from v2.                                                                                           |
| `get_customer_cues(...)`    | **REFIT**                       | This is worth keeping conceptually. Cross-slice callers really may need a compact, PII-free Customer gating view. But it must call real services and expose current truth: `eligibility_complete`, tier unlocks, Tier 1 urgency, maybe veteran/homeless qualifiers.                                                                          | Keep function idea, rebuild implementation and DTO.                                                          |
| `get_needs_profile(...)`    | **REFIT**                       | Worth keeping in spirit, but current DTO is too weak and implementation calls non-existent services. It should become the honest read for staged readiness / assessment posture.                                                                                                                                                             | Rebuild around real services and new model fields.                                                           |
| `get_dashboard_view(...)`   | **REMOVE current form**         | The current name and current DTO both imply a much richer public contract than you actually want. Better to kill this shape than harden a misleading one.                                                                                                                                                                                    | Replace with something smaller like `get_customer_summary(...)` if you still want a general read seam.       |
| `append_history_entry(...)` | **KEEP and IMPLEMENT**          | This is the one absolutely essential write seam in the current file. It matches the direction you just pinned for CustomerHistory. The service already exists.                                                                                                                                                                               | Keep, validate input, call customer service `append_history_entry(...)`, normalize errors.                   |

# What survives from the current contract, in plain English

## Survives in spirit

These are real needs:

- a **small cross-slice cues read**

- a **needs/assessment snapshot read**

- a **history append write**

## Does not survive as-is

These are scaffolding ghosts:

- the rich dashboard object

- dead write result DTOs

- dead write constants

- the deprecated `get_profile()` stub

# My recommended first-pass published surface

If we were rewriting `customers_v2` right now, I would narrow it to this:

## Read

- `get_customer_cues(entity_ulid)`

- `get_assessment_snapshot(entity_ulid)`  
  or keep the name `get_needs_profile(...)` if you want, but the DTO must change

## Write

- `append_history_entry(...)`

That is enough to support the hardened center of the slice without publishing a fake universe.

# What I would rename

You did not ask for renames, but two are worth saying out loud.

## `get_dashboard_view`

I would not keep that name publicly.

It invites scope creep. Better options:

- `get_customer_summary`

- `get_customer_status`

- `get_customer_overview` only if it stays small

## `get_needs_profile`

This name is acceptable, but your current philosophy is now more precise than “profile.”

Better options:

- `get_assessment_snapshot`

- `get_service_readiness`

- `get_customer_cues` for the smaller one, and `get_assessment_snapshot` for the richer one

# The two most obvious cut lines

If you want the fastest truth pass, cut these first:

## Cut line 1: delete dead scaffolding

Remove:

- `VerificationResultDTO`

- `TierUpdateResultDTO`

- `WHERE_VERIFY_VETERAN`

- `WHERE_UPDATE_TIER1`

- `WHERE_UPDATE_TIER2`

- `WHERE_UPDATE_TIER3`

- `get_profile(...)`

## Cut line 2: replace the fake dashboard

Delete the current `DashboardDTO` + current `get_dashboard_view(...)` shape and replace it with a smaller real DTO.

That one move alone will clear a lot of fog.

# My recommendation for the next concrete step

The cleanest next move is:

**I draft the replacement `customers_v2` symbol list and DTO field list from scratch, using only the symbols we decided should survive.**

That would give you a true target before any code refit starts.
