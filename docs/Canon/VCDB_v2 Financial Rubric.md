# VCDB v2 Financial Rubric — Target State Rewrite

This rewrite locks down the Calendar ↔ Governance ↔ Sponsors ↔ Finance
seam so semantic ownership stays clear while the money trail stays fully
traceable.

---

## 0) Target State in One Paragraph

Calendar owns planning, draft funding demands, published funding demands,
and execution requests. Governance owns semantic meaning, fund/restriction
rules, approval logic, and publish-time semantic packaging. Sponsors owns
fundraising intent and realization handoff. Finance owns reserves,
encumbrances, postings, journals, and reporting truth. The canonical join
handle across the entire pipeline is `funding_demand_ulid`, while actual
spend should usually anchor to `encumbrance_ulid` once money has been
committed.

---

## 1) Non-Negotiable Ownership Rules

### Calendar owns

- Project planning.
- Draft funding demands.
- Published funding demands.
- The canonical stored published-demand package.
- Discovery of published funding demands for Sponsors.
- Execution/disbursement requests against a published demand.

### Governance owns

- Semantic keys and validation.
- Fund eligibility and restriction posture.
- Approval requirements.
- Publish-time semantic packaging attached to a funding demand.
- Decision fingerprints for preview/approval outputs.
- Downstream realization rules and receive/bridge posture.

### Sponsors owns

- Prospects, pledges, and funding intent.
- Realization of incoming support against a published funding demand.
- Sponsor-side metadata and relationship truth.
- Handoff of realized support into Finance using explicit published semantics.

### Finance owns

- Money truth.
- Fund balances.
- Reserves.
- Encumbrances.
- Journal and journal-line postings.
- Expense and income posting facts.
- Reporting and drilldown over posted facts.

### What must never happen

- Calendar must not invent or reinterpret Governance semantic meaning after
  publish.
- Sponsors must not invent accounting line construction.
- Finance must not reconstruct semantic meaning from only `project_ulid`.
- Governance must not reference Finance account codes or Finance schema.

---

## 2) The Core Canonical Objects

### A) Draft Funding Demand (Calendar-owned)

A planning object. It expresses:

- what work is being planned,
- how much funding appears needed,
- candidate spending class,
- candidate tags,
- candidate source profile,
- project/operator planning hints.

Draft demands are not yet canonical semantic truth.

### B) Published Funding Demand (Calendar-owned, Governance-packaged)

A frozen published package. This is the canonical downstream funding-demand
object consumed by Sponsors and reused by Calendar when execution begins.

It contains:

- Calendar-owned planning snapshot.
- Governance-owned semantic package.
- Governance-published downstream realization cues.
- Immutable identifiers and publish timestamp.

### C) Funding Intent (Sponsors-owned)

A promise or expected support fact:

- prospect,
- pledge,
- expected grant,
- expected reimbursement,
- expected in-kind offset.

It is not money truth.

### D) Money Facts (Finance-owned)

Real financial facts:

- income postings,
- reserve entries,
- encumbrances,
- expense postings,
- relief of encumbrances,
- reimbursement receipts,
- ops support allocations and repayments.

---

## 3) The Join Handles

### Required global handle

`funding_demand_ulid`

This is the canonical trace handle from draft publication forward.

### Required supporting handles

- `project_ulid` — reporting and planning anchor.
- `source_ref_ulid` — caller/source trace anchor.
- `decision_fingerprint` — Governance preview/decision trace.
- `encumbrance_ulid` — the preferred spend anchor after commitment.

### Rule

`project_ulid` alone is never sufficient to determine posting semantics for
execution spending.

A project may have:

- multiple funding demands,
- multiple fund codes,
- multiple restriction postures,
- multiple realization paths over time.

Therefore:

- income must carry `funding_demand_ulid`,
- reserve must carry `funding_demand_ulid`,
- encumbrance must carry `funding_demand_ulid`,
- expense must carry `funding_demand_ulid`, and should normally also carry
  `encumbrance_ulid`.

---

## 4) The Published Funding Demand Package

Calendar should remain the canonical keeper of the published funding-demand
package. Finance should not become the keeper of the full package.

### 4.1 Calendar-owned section: `planning`

This is the frozen planning snapshot:

- `project_title`
- `summary`
- `scope_summary`
- `spending_class`
- `tag_any`
- `source_profile_key`
- `ops_support_planned`
- `planning_basis`

These values explain what was being planned at publish time.

### 4.2 Governance-owned section: `policy`

This is the frozen semantic package attached at publish time:

- `decision_fingerprint`
- `eligible_fund_codes`
- `default_restriction_keys`
- `approved_tag_any`
- `source_profile_summary`

These values are canonical semantic truth for downstream consumers.

### 4.3 Governance-owned downstream section: `workflow`

This section should be treated as Governance-published downstream cues, not
Calendar-authored finance logic.

It currently expresses things like:

- `receive_posture`
- `reserve_on_receive_expected`
- `reimbursement_expected`
- `bridge_support_possible`
- `return_unused_posture`
- `recommended_income_kind`
- `allowed_realization_modes`

### Naming recommendation

Later, rename `workflow` to one of:

- `realization_policy`
- `published_governance_cues`
- `downstream_cues`

Reason: the current word `workflow` obscures ownership and makes it sound like
Calendar execution state rather than Governance-published downstream guidance.

### 4.4 Demand/origin section

The package must also preserve:

- `funding_demand_ulid`
- `project_ulid`
- `title`
- `status`
- `goal_cents`
- `deadline_date`
- `published_at_utc`
- `demand_draft_ulid`
- `budget_snapshot_ulid`

---

## 5) Lifecycle Pipeline (Locked)

### Stage A — Draft Demand Creation (Calendar)

Calendar creates and edits the draft funding demand.

Inputs may include:

- project scope,
- amount goal,
- candidate spending class,
- candidate tags,
- candidate source profile,
- ops support planning hints.

At this stage, these are planning inputs, not canonical semantic truth.

### Stage B — Publish-Time Semantic Packaging (Calendar → Governance → Calendar)

When a demand is published:

1. Calendar submits the draft planning inputs.
2. Governance validates and resolves semantic meaning.
3. Governance returns the approved semantic package and decision fingerprint.
4. Calendar stores the frozen published funding-demand package.

Important rule:

Publication is the moment semantic truth becomes frozen for the demand.

### Stage C — Demand Discovery (Sponsors reads Calendar)

Sponsors must read published funding demands from Calendar.

Sponsors is responding to a published need, so the source of truth is the
Calendar-owned published demand package, not a Finance projection and not raw
Governance policy state.

### Stage D — Intent Tracking (Sponsors)

Sponsors records prospects, pledges, and related intent against the published
funding demand.

No Finance posting happens yet.

### Stage E — Realization / Receipt (Sponsors → Governance preview → Finance)

When support actually lands:

1. Sponsors reads the published package.
2. Sponsors resolves or confirms fund code and receipt path.
3. Governance previews the receive decision using the published package.
4. Finance posts income using explicit semantic inputs.
5. Finance optionally records a reserve when policy/defaults expect it.

Result:

- Calendar remains keeper of the published demand.
- Governance remains owner of semantic meaning.
- Finance records money truth.

### Stage F — Funding Availability (Finance)

Finance computes and exposes execution truth for the demand:

- received,
- reserved,
- encumbered,
- spent,
- remaining,
- funded enough / not funded enough.

Calendar may read this truth, but does not own it.

### Stage G — Commit / Encumber (Calendar → Governance preview → Finance)

When Calendar is ready to commit spending:

1. Calendar reads the published demand package it already owns.
2. Calendar reads Finance execution truth / availability.
3. Calendar chooses the explicit funding lane.
4. Governance previews the encumber decision.
5. Finance records the encumbrance.

Encumbrance should be tied to:

- `funding_demand_ulid`
- `project_ulid`
- `fund_code`
- `decision_fingerprint`
- source reference

### Stage H — Disbursement / Expense (Calendar → Finance)

When the real bill, invoice, or receipt arrives:

1. Calendar submits the expense against the demand.
2. Expense should normally reference `encumbrance_ulid`.
3. Finance posts the expense and relieves the encumbrance.

Key rule:

Expense posting must not rely on `project_ulid` alone to rediscover semantics.
It should use the already selected funding lane, and ideally the existing
encumbrance.

### Stage I — Reporting

Reports should be queryable by:

- `funding_demand_ulid`
- `project_ulid`
- `fund_code`
- `restriction_keys`
- `income_kind`
- `expense_kind`
- `encumbrance_ulid`
- time window

---

## 6) Required Inputs to Finance (Locked)

### 6.1 `post_income(...)`

Required:

- `amount_cents`
- `happened_at_utc`
- `fund_code`
- `fund_label`
- `fund_restriction_type`
- `income_kind`
- `receipt_method`
- `source`
- `funding_demand_ulid`

Strongly recommended:

- `project_ulid`
- `source_ref_ulid`
- `payer_entity_ulid`
- `memo`
- `request_id`
- `decision_fingerprint` if available at the handoff layer

Rule:

Finance posts income from explicit semantics. It does not infer semantics from
Project alone.

### 6.2 `reserve_funds(...)`

Required:

- `funding_demand_ulid`
- `fund_code`
- `amount_cents`
- `source`

Recommended:

- `project_ulid`
- `source_ref_ulid`
- `memo`
- `request_id`

### 6.3 `encumber_funds(...)`

Required:

- `funding_demand_ulid`
- `fund_code`
- `amount_cents`
- `source`

Recommended and practically expected:

- `project_ulid`
- `source_ref_ulid`
- `decision_fingerprint`
- `memo`
- `request_id`

Rule:

Encumbrance is the normal bridge between planned demand execution and actual
expense posting.

### 6.4 `post_expense(...)`

Required:

- `amount_cents`
- `happened_at_utc`
- `fund_code`
- `fund_label`
- `fund_restriction_type`
- `expense_kind`
- `payment_method`
- `source`
- `funding_demand_ulid`

Strongly recommended:

- `project_ulid`
- `source_ref_ulid`
- `encumbrance_ulid`
- `memo`
- `request_id`

Rule:

For committed execution spending, `encumbrance_ulid` should normally be present.
If absent, the call is still allowed only when the expense is truly direct spend
rather than spend against a prior commitment.

---

## 7) What Calendar Must Preserve

Calendar must preserve the published funding-demand package because Calendar is
canonical owner of the published demand object.

Calendar must therefore be able to answer:

- what was published,
- what planning snapshot backed it,
- what Governance semantic package was attached,
- what downstream realization cues were attached,
- what source profile drove the package,
- what demand this later encumbrance/expense belongs to.

Finance may keep denormalized trace echoes for audit convenience, but those are
not the authoritative published-demand package.

---

## 8) What Sponsors Must Read

Sponsors should query Calendar for published funding demands and their published
packages.

Sponsors should not look to Finance to discover needs.

Finance can answer:

- what has been received,
- what is reserved,
- what is encumbered,
- what has been spent.

But Finance should not be the catalog of published mission needs.

---

## 9) What Calendar Must Use to Build Disbursement Demands

Calendar should build disbursement requests from two truths together:

### A) Calendar truth

The frozen published funding-demand package.

### B) Finance truth

Live availability and commitment state, including:

- open reserves,
- open encumbrances,
- fund availability by demand,
- prior receipts/spend.

Therefore Calendar is not inventing semantic meaning during disbursement. It is
combining:

- the already-published Governance-approved demand package,
- with current Finance execution truth.

That is the proper seam.

---

## 10) Boundary Tests (Use these as drift tripwires)

If any answer becomes “yes,” the seam is drifting:

1. Can Finance post a demand-linked expense using only `project_ulid` and no
   `funding_demand_ulid`?
2. Can Calendar recompute publish-time realization rules after publication
   without going back through Governance?
3. Can Sponsors realize support without consuming the published demand package?
4. Can Governance policy changes rewrite the meaning of an already published
   demand in place?
5. Can Finance become the only place where the published demand context still
   exists?
6. Can Calendar choose journal accounts or accounting line construction?
7. Can Sponsors choose debit/credit lines?

All of those must remain “no.”

---

## 11) Implementation Cleanup Order

1. Remove the backward-compat `preview_funding_decision` shim once all callers
   use explicit DTO requests.
2. Keep `FundingDemandContextDTO` / published package semantics explicit at the
   Calendar contract boundary.
3. Move any publish-time downstream cue derivation out of ambiguous
   Calendar-owned language and document it as Governance-published.
4. Keep `services_finance_bridge.py` focused on:
   - reading published demand package,
   - reading Finance truth,
   - building explicit Governance preview requests,
   - calling Finance with explicit inputs.
5. Restore the focused encumber preview seam test.
6. Add drift tests proving:
   - published demand remains Calendar-owned,
   - Finance requires `funding_demand_ulid`,
   - expense against commitment prefers `encumbrance_ulid`,
   - Sponsors reads published demand package from Calendar,
   - disbursement does not infer semantics from `project_ulid` alone.

---

## 12) Operations Support / OpsFloat Alignment

Operations support remains a Finance-owned money fact and a Governance-governed
policy posture, but Project purpose is still anchored in Calendar via:

- `funding_demand_ulid`
- `project_ulid`

That means:

- `ops-seed`,
- `ops-backfill`, and
- `ops-bridge`

must remain traceable to the destination funding demand and project.

Publication alone does not create funded truth. A demand/project becomes funded
only when Finance records real support facts such as:

- income,
- reserve,
- encumbrance,
- or explicit ops support allocation.

---

## 13) One-Screen Summary

### Calendar

Plans the work, publishes the demand, stores the published package, and later
requests execution.

### Governance

Decides what the semantic package means and what actions are allowed.

### Sponsors

Finds published needs, tracks intent, and turns landed support into explicit
Finance posting inputs.

### Finance

Records the money truth and never has to guess what demand an expense belongs
to.

---

## 14) Plain-English Rule

Calendar keeps the published mission need.
Governance defines what that need means in funding terms.
Sponsors helps land support for that need.
Finance records what actually happened to the money.

The demand package lives with Calendar.
The money trail lives with Finance.
They meet on `funding_demand_ulid`, and actual spend should usually meet on
`encumbrance_ulid` too.
