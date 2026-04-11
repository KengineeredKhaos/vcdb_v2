# VCDBv2 Application Overview

## System Shape, Relationships & Money Flow Guide

This guide explains the shape of the application in plain English. It is meant
to help a future operator or successor developer understand what each slice is
for, how they fit together, and which invariants matter most.

This guide is a descriptive overview designed only to introduce the essential system "bones". The detailed concepts, foundations and Invariant rules live in the Ethos document.

---

## 1) What VCDB v2 is trying to be

VCDB v2 is a vertically sliced application built for a small, local,
operator-driven organization. It is designed to be:

- auditable
- durable
- simple enough to inherit
- explicit about ownership
- resistant to hidden side effects

The core idea is straightforward:

- **Entity** is the identity spine
- **Operational slices** record facts about people, providers, sponsors,
  projects, and goods
- **Governance** defines the rulebook
- **Finance** records money truth
- **Ledger** records non-PII audit truth
- **Admin** is the operator control surface

The system is meant to preserve a durable paper trail while still being usable
by ordinary operators.

---

## 2) The slices in one pass

### Entity

Entity is the identity backbone.

It holds the canonical person and organization identity, and it is the only
slice that should own ordinary PII. Other slices refer back to Entity by ULID.

### Customers

Customers owns customer-domain truth:

- eligibility
- needs assessment
- service readiness
- customer-facing history references

It does not own canonical identity/contact/address PII. That remains in
Entity.

### Resources

Resources owns provider and capability truth:

- what an organization can provide
- onboarding state
- capability and capacity descriptors
- provider-side relationship data

### Sponsors

Sponsors owns fundraising and relationship work:

- sponsor profile hints
- cultivation posture
- pledges and funding intent
- realized support handoff to Finance

Sponsors is about intent and relationships, not accounting mechanics.

### Calendar

Calendar owns work intent and execution planning:

- projects
- tasks
- budget snapshots and budget lines
- demand drafts
- published funding demands
- execution-triggered finance requests

Calendar answers the question, “What work are we trying to do, and what does it
need?”

### Logistics

Logistics owns inventory and operational movement facts:

- SKUs
- stock positions
- movements
- issuance and reconciliation flows

### Finance

Finance is the money book of record.

It owns:

- journals and journal lines
- reserves
- encumbrances
- spend
- availability and reporting truth

If something is a real money fact, Finance owns it.

### Governance

Governance is the rulebook.

It owns:

- taxonomy-backed policy files
- validation and approval rules
- thresholds, caps, and semantic controls

It does not own another slice’s schema or data storage.

### Ledger

Ledger is the audit spine.

It records semantic events with ULIDs and field names, not PII values.

### Admin

Admin is the operator control surface.

It is the place where trusted operators:

- review status
- triage issues
- inspect reports
- supervise cron and maintenance
- launch the correct owning-slice workflow

Admin is not supposed to become a second business layer.

---

## 3) The major ownership split

A lot of the system becomes easier to understand when you group it by role.

### Identity truth

Entity owns who the person or organization is.

### Operational truth

Customers, Resources, Sponsors, Calendar, and Logistics each own their own
slice-local facts and workflows.

### Rule truth

Governance owns policy and semantic approval rules.

### Money truth

Finance owns actual money facts.

### Audit truth

Ledger owns the non-PII audit trail.

### Operator oversight

Admin owns the human-facing control surface.

That ownership split is the backbone of the whole application.

---

## 4) How cross-slice work is supposed to happen

VCDB v2 deliberately avoids direct cross-slice reach-arounds.

Instead, slices talk through contracts.

The normal pattern is:

1. a route or CLI command starts the work
2. the owning slice service performs the business logic
3. if another slice is needed, the call goes through an extension contract
4. DTOs cross the seam
5. the route or CLI owns commit/rollback

This is how the system keeps one slice from silently becoming dependent on
another slice’s private schema or helper functions.

---

## 5) Customers, Resources, and Logistics in the service story

Customers, Resources, and Logistics participate in the same service story, but
they do not own the same truth.

### Customers

Customers owns the customer-domain picture:

- eligibility
- needs assessment
- service readiness
- customer-facing service history

Customers does not own canonical identity/contact/address PII, and it does not
own provider capability truth or stock truth.

### Resources

Resources owns provider-side truth:

- what an organization says it can do
- capability and capacity descriptors
- provider-side onboarding state
- provider-side relationship data

Resource capability vocabulary is intentionally not the same thing as Customer
need vocabulary. Customer need keys describe broad human-need buckets. Resource
capability keys describe concrete provider offerings. The matching layer is
where those two vocabularies are deliberately bridged.

### Logistics

Logistics owns tangible fulfillment truth:

- inventory
- stock positions
- movements
- issuance
- reconciliation

When a Customer need is met by stocked goods rather than by an outside provider,
Logistics becomes the fulfillment slice for that part of the story.

### The relationship in plain English

The practical flow is:

1. Customers records the customer's condition and need.
2. Resources helps answer who can serve that need when the answer is an outside
   provider or partner capability.
3. Logistics helps answer what can be issued immediately when the answer is a
   stocked item or material support.
4. Customers remains the place where the customer-facing service story is
   summarized, while the operational truth remains owned by the slice that
   performed the work.

This keeps the design honest:

- Customers owns customer condition and service narrative.
- Resources owns provider capability truth.
- Logistics owns physical issuance and movement truth.

### Referral and fulfillment posture

At the current baseline, referrals and referral outcomes are documented
interactions, not heavyweight workflow objects. A referral to a Resource
provider and a fulfillment action from Logistics are reflected back into the
Customer story through Ledger events and CustomerHistory narrative entries,
rather than through a sprawling cross-slice workflow engine.

That posture favors:

- auditable facts
- clear ownership
- human-readable service history

over premature workflow bureaucracy.

---

## 6) Point of Contact entities and organization relationships

Point of Contact entities are ordinary person entities used in an
organization-supporting role. They are not operators, not customers, and in the
normal case should be treated as civilian-domain persons linked to an
organization for communication and coordination purposes.

### What Entity owns

Entity owns the person's core identity:

- the canonical person ULID
- person/contact truth that properly belongs in the identity spine
- small read-only contact-card style projections when another slice needs to
  display the person

Entity does not own organization-side POC relationships.

### What Resources and Sponsors own

The organization slice owns the organization-to-POC relationship.

That means:

- Resources owns Resource-organization POC links.
- Sponsors owns Sponsor-organization POC links.

The relationship tables live and mutate inside the owning org slice, not inside
Entity.

### Why this matters

A POC is not "someone with system authority." A POC is a real person VCDB may
need to call, email, or reference in connection with an organization.

That keeps the model grounded:

- operators are system users
- customers are service recipients
- resource and sponsor organizations are partner entities
- POCs are linked civilian persons who help VCDB interact with those
  organizations

This avoids turning Entity into a universal relationship manager and keeps
organization workflows local to the slice that actually needs them.

---

## 7) The funding and execution story

The application’s money and project story is now organized around one
Calendar-centered demand pipeline.

### The pipeline

Project  
→ Task planning  
→ Budget Snapshot / Budget Lines  
→ Demand Draft  
→ Governance semantic review  
→ approved semantics returned to Calendar  
→ published FundingDemand  
→ Sponsors fulfillment work  
→ Finance recognition and availability truth  
→ Calendar execution against recognized support

### Why this matters

This pipeline separates four different things that are easy to confuse:

- work to be done
- semantic approval
- fundraising intent
- actual money truth

That separation is the reason the design stays readable.

---

## 8) Funding Demand, Funding Intent, and Money Fact

These are three different objects and must stay different.

### Funding Demand

Owned by Calendar.

A Funding Demand is a requirement. It says a project needs money. It is not
itself money.

### Funding Intent

Owned by Sponsors.

A Funding Intent is a promise, prospect, or expectation. It still is not money.

### Money Fact

Owned by Finance.

A Money Fact is a real accounting event:

- income received
- reserve created
- encumbrance posted
- expense posted
- reimbursement recognized

This separation is one of the most important mental models in the application.

---

## 9) Why the `funding_demand_ulid` matters

The application uses one trace handle to connect the whole funding story:
`funding_demand_ulid`.

That ULID can follow the lifecycle through:

- published demand
- sponsor intent
- realized support
- reserves
- encumbrances
- expenses
- reporting

This lets you reconstruct the whole chain for one demand without inventing
parallel identifiers all over the system.

---

## 10) Calendar’s role in the funding pipeline

Calendar owns the work story.

That includes:

- project planning truth
- task planning truth
- budget development truth
- demand draft assembly
- published-demand provenance
- execution state

Calendar does not own money truth.

Instead, Calendar creates and publishes the demand, then later asks Finance to
encumber or spend against recognized support as the project moves into
execution.

---

## 11) Governance’s role in the funding pipeline

Governance does not invent the demand.

Governance reviews the demand package Calendar assembled and returns one of two
things:

- a return-for-revision decision
- an approved semantic package

That approved package is then frozen by Calendar into the published demand
artifact.

In other words, Governance owns semantic approval truth, not demand authorship.

---

## 12) Sponsors’ role in the funding pipeline

Sponsors consumes published demands and performs sponsor-side work:

- finding prospects
- recording pledges
- tracking cultivation
- realizing support
- handing realized support into Finance

Sponsors is not supposed to create project demands or choose accounting lines.

It works from the published demand package that Calendar already froze.

---

## 13) Finance’s role in the funding pipeline

Finance owns money recognition and availability truth.

That includes:

- income recognition
- reserves
- encumbrances
- spend
- availability posture
- remaining open amount
- reporting truth

Finance is also where Calendar looks back when it needs to know whether a
demand is funded enough to execute honestly.

---

## 14) Published context and execution truth

Two snapshots matter a lot in the current design.

### Published context

The published demand carries a frozen, publish-time context package assembled
from Calendar facts plus Governance-approved semantics.

Sponsors and Finance read that as context. They do not treat it as live policy
or money truth.

### Execution truth

Finance provides execution truth back to Calendar:

- recognized support totals
- encumbered amount
- spent amount
- remaining open amount
- funded-enough posture
- support-source posture

That lets Calendar show honest project posture without pretending to own the
book of record.

---

## 15) OpsFloat and operations support

Operations support is allowed, but it is not a secret side channel.

The core rule is:

Project remains the purpose anchor. Operations support must be explicit and
auditable.

Allowed modes are:

- `ops-seed`
- `ops-backfill`
- `ops-bridge`

Important consequences:

- publication alone does not mean funded
- operations support is never implicit
- reimbursement or replenishment rules must be explicit
- petty cash is not part of OpsFloat

---

## 16) Why Admin exists

As the system grew, it became clear that some slices were not really meant to
be direct human workspaces.

Finance, Ledger, and Governance especially are better treated as
infrastructure-backed truth systems with Admin as the operator-facing control
surface.

That is why Admin is framed as:

- dashboard
- inbox
- reports
- cron supervision
- policy workflow shell
- launchpad into owning-slice workflows

This keeps the real semantics in the owning slices while still giving trusted
operators one place to see what is happening.

---

## 17) How access is supposed to feel

The access model has two layers.

### RBAC

RBAC determines who may enter a surface.

### Domain or governance authority

Some actions, especially approvals or overrides, require additional authority
once the actor is already inside the surface.

The guiding rule is:

**RBAC gets you to the door. Authority decides whether you may make certain
decisions once inside.**

That distinction keeps the permission model from turning into mush.

---

## 18) What “good behavior” looks like in this app

When the system is behaving properly, you should be able to say:

- which slice owns a given fact
- why a cross-slice call happened
- which ULIDs connect the story
- which `request_id` ties together the effects of one action
- which ledger events were emitted
- which policy or approval semantics applied
- what remained merely intent, and what became truth

That is the real shape of the application.

---

## 19) A practical mental model for successors

If a future maintainer gets lost, the recovery questions should be:

1. What kind of truth is this?
   
   - identity
   - operational fact
   - policy
   - money
   - audit
   - operator oversight

2. Which slice owns that truth?

3. Is the current object:
   
   - demand
   - intent
   - money fact
   - audit event
   - report or projection

4. Is this live truth, frozen context, or a human-facing summary?

Those four questions will usually point to the right slice and the right seam.
