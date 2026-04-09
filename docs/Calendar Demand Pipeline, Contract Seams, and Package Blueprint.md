# Calendar Demand Pipeline, Contract Seams, and Package Blueprint

**VCDB v2 — working thread spec**

## 1. Purpose

This document describes the Calendar-centered demand pipeline for VCDB v2, the contract seams between slices, and the expected data packages that pass through those seams.

This is a **human-readable design spec**, not a final code contract. Its purpose is to keep all follow-on thread work aligned while Governance, Sponsors, and Finance contracts are repaired around the now-established Calendar internal pipeline.

---

## 2. Core pipeline narrative

The canonical flow is:

**Project**  
→ **Tasks**  
→ **Budget Snapshot / Budget Lines**  
→ **Demand Draft**  
→ **Governance semantic review**  
→ **approved semantics returned to Calendar**  
→ **published FundingDemand**  
→ **Sponsors seeks fulfillment**  
→ **Finance recognizes available support and records money facts**  
→ **Calendar executes project work and sends expenses to Finance**

### Plain-English version

Calendar begins with a Project and a set of Tasks that describe the work to be performed.

Calendar develops a budget for that work using Budget Snapshots and Budget Lines. A locked Budget Snapshot becomes the financial basis for a Demand Draft.

Calendar submits that Demand Draft to Governance for semantic review. Governance does not invent the demand. Governance reviews the demand Calendar assembled, validates/attaches semantic tags, and either returns it for revision or approves it for publish.

Once approved, Calendar promotes the Demand Draft into a published FundingDemand. That published demand becomes the official ask that downstream slices consume.

Sponsors does not create demands. Sponsors consumes published Calendar demands and seeks fulfillment.

Finance does not create demands. Finance records the money facts that make support available to the Project and processes project expenses against that support.

Calendar consumes the recognized support and uses it to move the Project into execution.

---

## 3. Slice responsibilities

### Calendar owns

- Project planning truth

- Task planning truth

- Budget development truth

- Demand Draft assembly

- Published demand provenance

- Project execution state

### Governance owns

- Semantic review rules

- Policy validation

- Approval / return-for-revision decision

- Approved semantic payload returned to Calendar

### Sponsors owns

- Fulfillment work against published demand

- Sponsor-facing pursuit, commitment, realization, and follow-through

- Forwarding realized support into Finance-compatible form

### Finance owns

- Money recognition truth

- Encumbrance truth

- Spend truth

- Available support truth

- Loss / reimbursement / replenishment mechanics

---

## 4. Internal Calendar objects

### Project

The aggregate root for the whole planning and execution story.

### Task

A unit of work to be performed. Tasks describe work, not canonical money truth.

### Budget Snapshot

A stable cost picture for a Project at a given moment.

### Budget Line

A cost or offset component inside a Budget Snapshot. A line may be tied to a Task or be project-common.

### Demand Draft

The pre-publish ask assembled by Calendar from a locked Budget Snapshot and submitted for Governance review.

### FundingDemand

The published demand artifact created from an approved Demand Draft. This is the official downstream-facing ask.

---

## 5. Canonical invariants

These are the non-negotiables for the new pipeline.

### Demand creation invariants

- No published FundingDemand exists without a Demand Draft.

- No Demand Draft exists without a locked Budget Snapshot.

- No published FundingDemand exists without Governance-approved semantics.

### Budget invariants

- Budget totals come from Budget Lines, not manual total entry.

- Locked Budget Snapshots are immutable.

- Reuse occurs by copy-forward into a new Snapshot, not by sharing live Budget Lines across snapshots.

### Demand lifecycle invariants

- Demand Draft is the only pre-publish demand artifact.

- Published FundingDemand is not a draft-stage object.

- Published FundingDemand does not revert to draft.

### Ownership invariants

- Calendar owns planning truth.

- Governance owns semantic approval truth.

- Sponsors owns fulfillment truth.

- Finance owns money-recognition truth.

---

## 6. Status truth

### Project status

Project status describes where the work itself sits in the planning/execution lifecycle.

Canonical values:

- `draft_planning`

- `tasking_in_progress`

- `budget_under_development`

- `budget_ready`

- `execution_underway`

- `closeout_pending`

- `closed`

### Demand Draft status

Demand Draft status describes pre-publish preparation and Governance review.

Canonical values:

- `draft`

- `ready_for_review`

- `governance_review_pending`

- `returned_for_revision`

- `approved_for_publish`

### FundingDemand status

FundingDemand status describes the published/execution-facing demand lifecycle.

Canonical values:

- `published`

- `funding_in_progress`

- `funded`

- `executing`

- `closed`

### Meaning of `funded`

`funded` means the demand’s required amount is fully covered by finance-recognized support that is actually available to execute against, but execution has not yet begun. The money side is real enough that Calendar may proceed to execution when ops is ready.

Operators do not manually mark a demand as funded. Calendar determines funded state from recognized support posture.

---

## 7. Contract seam map

There are five primary seams.

### Seam 1: Calendar → Governance

Calendar submits a Demand Draft package for semantic review.

### Seam 2: Governance → Calendar

Governance returns semantic decision and publishability.

### Seam 3: Calendar → Sponsors

Calendar exposes a published demand package for fulfillment work.

### Seam 4: Sponsors → Finance

Sponsors forwards realized support in a Finance-digestible form.

### Seam 5: Finance → Calendar

Finance exposes recognized support, encumbrance, spend, and availability truth back to Calendar so the Project can execute honestly.

### Seam 6: Calendar → Finance

**Producer:** Calendar  
**Consumer:** Finance  
**Trigger:** Project needs encumbrance or disbursement during execution

---

## 8. Package blueprints

The DTO names below are working names, not final code names.

## 8.1 Internal Planning Package

**Producer:** Calendar  
**Consumer:** Calendar  
**Trigger:** Project planning / budgeting activity

This package is the internal planning basis that ultimately feeds the Demand Draft.

### Minimum contents

- `project_ulid`

- `project_title`

- `project_status`

- `task_refs`

- `budget_snapshot_ulid`

- `budget_snapshot_label`

- `scope_summary`

- `gross_cost_cents`

- `expected_offset_cents`

- `net_need_cents`

- `budget_line_refs`

- `source_profile_key` candidate

- `ops_support_planned`

- `spending_class_candidate`

- planning notes / assumptions

### Purpose

This package answers:  
**What are we trying to do, what will it cost, and what funding posture do we think applies?**

---

## 8.2 Governance Review Package

**Producer:** Calendar  
**Consumer:** Governance  
**Trigger:** Demand Draft submitted for review

This is the package Calendar sends to Governance for semantic tagging and publish approval.

### Minimum contents

- `demand_draft_ulid`

- `project_ulid`

- `budget_snapshot_ulid`

- `requested_amount_cents`

- `title`

- `summary`

- `scope_summary`

- `needed_by_date`

- `source_profile_key` candidate

- `ops_support_planned`

- `spending_class_candidate`

- `tag_any`

- provenance references back to planning basis

### Purpose

This package answers:  
**Please review this ask, validate/attach semantics, and tell Calendar whether it may publish.**

### Invariants before crossing this seam

- Demand Draft exists

- linked Budget Snapshot is locked

- requested amount is set

- project and snapshot provenance is intact

---

## 8.3 Governance Decision Package

**Producer:** Governance  
**Consumer:** Calendar  
**Trigger:** Governance review decision

This is the package Governance sends back to Calendar.

### Minimum contents

- `decision`
  
  - approved
  
  - returned_for_revision

- `governance_note`

- `approved_spending_class`

- `approved_source_profile_key`

- `eligible_fund_codes`

- `default_restriction_keys`

- `approved_tag_any`

- validation errors, if returned

### Purpose

This package answers:  
**These are the approved semantics Calendar may freeze into the published demand, or the reasons the draft must be revised.**

### Ownership

- Governance owns the meaning of this package

- Calendar stores and applies it

---

## 8.4 Published Demand Package

**Producer:** Calendar  
**Consumer:** Sponsors and downstream readers  
**Trigger:** Approved Demand Draft promoted to FundingDemand

This is the official downstream-facing ask.

### Minimum contents

- `funding_demand_ulid`

- `project_ulid`

- `demand_draft_ulid`

- `budget_snapshot_ulid`

- `title`

- `summary`

- `scope_summary`

- `goal_cents`

- `status`

- `published_at`

- planning facts
  
  - `source_profile_key`
  
  - `ops_support_planned`

- approved semantics
  
  - `spending_class`
  
  - `eligible_fund_codes`
  
  - `default_restriction_keys`
  
  - `tag_any`

- provenance / origin block

### Purpose

This package answers:  
**This is the official published ask that Sponsors may pursue and Finance may later recognize against.**

### Important note

This is not a draft wrapper. It is a published artifact.

---

## 8.5 Sponsor Fulfillment Package

**Producer:** Sponsors  
**Consumer:** Finance  
**Trigger:** Support is realized or committed in a way Finance can record

This package is not fully finalized in this thread, but the seam is defined now.

### Expected minimum contents

- `funding_demand_ulid`

- `project_ulid`

- `sponsor_ulid`

- `support_mode`
  
  - grant
  
  - direct support
  
  - reimbursement
  
  - in-kind
  
  - other allowed modes

- `amount_cents`

- restrictions / conditions

- realization date / effective date

- notes needed for Finance posting or recognition

### Purpose

This package answers:  
**Support has been realized for this published demand; Finance should recognize it accordingly.**

---

## 8.6 Finance Availability / Execution Package

**Producer:** Finance  
**Consumer:** Calendar  
**Trigger:** funding recognized, encumbered, spent, or relieved

This is what tells Calendar whether the Project can proceed honestly.

### Expected minimum contents

- `funding_demand_ulid`

- `project_ulid`

- recognized support totals

- encumbered amount

- spent amount

- remaining open amount

- funded-enough status

- support source posture
  
  - sponsor-funded
  
  - ops_float-supported
  
  - mixed

- timestamps / status notes

### Purpose

This package answers:  
**Here is the money truth Calendar may execute against.**

---

## 8.7 Calendar → Finance Encumber Request Package

**Purpose**  
Reserve available support for a Project before actual spending occurs.

### Minimum contents

- `funding_demand_ulid`
- `project_ulid`
- `budget_snapshot_ulid` or planning basis ref
- `requested_amount_cents`
- `spending_class`
- `source_profile_key`
- `eligible_fund_codes` if already approved
- `default_restriction_keys`
- `tag_any`
- `reason` / operator note
- `actor_ulid`
- `request_id`

### Finance response

- allowed / denied
- reason codes
- selected fund or support source
- approvals required or satisfied
- encumbrance record ref if created

---

## 8.8Calendar → Finance Disbursement / Spend Request Package

**Purpose**  
Record and pay an actual Project expense against recognized available support.

### Minimum contents

- `funding_demand_ulid`
- `project_ulid`
- `task_ulid` optional
- `expense_ref_ulid` or request ref
- `amount_cents`
- `expense_kind`
- `spending_class`
- `description`
- `payee` / vendor / resource ref as applicable
- `support_source_hint`
  - sponsor-funded
  - ops_float
  - mixed / unspecified
- `document_refs`
  - receipts, invoice refs, task refs, etc.
- `actor_ulid`
- `request_id`

### Finance response

- allowed / denied
- posted expense / disbursement ref
- resulting balances
- whether encumbrance was relieved
- remaining open amount on the demand





## 9. Ops Float clarification

Ops Float is **not** a new demand source, alternate seam, or replacement for Sponsor fulfillment.

Ops Float is one available funding vehicle that may be used after a demand already exists and has been semantically approved/published.

### Correct meaning

Ops Float means:

- Finance can temporarily allocate General Unrestricted funds, typically from Operations budget excess, to let a Project begin execution before Sponsor fulfillment lands.

- Sponsors still seeks fulfillment for the same published demand.

- Finance sets aside the ops-float money for the Project in anticipation that it may later be replaced by Sponsor fulfillment or reimbursement.

- Calendar spends against that available support as though the Project were funded enough to execute.

- Later, the float exposure may be:
  
  - replenished by Sponsor fulfillment,
  
  - held until grant reimbursement arrives,
  
  - backfilled,
  
  - or written off as loss/shortfall per policy and Finance treatment.

### What Ops Float is not

- not a new demand creator

- not a second demand pipeline

- not a substitute for Governance review

- not a substitute for Sponsor fulfillment work

- not an excuse to bypass Finance truth

### Practical implication

Ops Float belongs inside the same published-demand lifecycle. It changes support availability for a demand. It does not create the demand.

---

## 10. Failure and return paths

### Governance return path

If Governance returns a draft for revision:

- Demand Draft stays inside Calendar

- Draft status becomes `returned_for_revision`

- operator revises the Draft

- Draft re-enters review flow

### Publish denial path

No FundingDemand is published.

### Sponsor non-fulfillment path

Published demand remains open and may remain `funding_in_progress`.

### Ops Float path

If policy allows and Finance makes support available through ops_float:

- published demand may still proceed toward `funded` or at least execution-ready posture depending on recognized support truth

- Sponsors still pursues fulfillment

- Finance later reconciles the float exposure

---

## 11. What this document does not finalize yet

This document does **not** finalize:

- final DTO class names

- final contract method names

- exact Governance internals

- exact Sponsor realization contract

- exact Finance posting/recognition internals

Those will be repaired slice by slice in follow-on threads.

This document **does** finalize:

- the Calendar-centered demand pipeline narrative

- the seam order

- the ownership of meaning

- the package categories that must cross each seam

---

## 12. Thread handoff note

Use this document as the anchor for the next threads in this order:

1. **Calendar ↔ Governance contract repair**  
   Firm up Governance review submission and decision packages.

2. **Calendar ↔ Sponsors seam repair**  
   Firm up the published demand package Sponsors consumes.

3. **Sponsors ↔ Finance seam repair**  
   Firm up the fulfillment package Finance digests.

4. **Finance ↔ Calendar execution truth repair**  
   Firm up the support/encumber/spend package Calendar consumes.

---

This is the version I’d carry forward as the opening spec.
