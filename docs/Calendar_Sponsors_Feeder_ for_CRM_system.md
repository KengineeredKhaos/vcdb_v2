# Sponsors Slice: Reasoning on a Revision

Sponsors needs a reliable, detailed source of Project Funding data from Calendar for CRM planning and income reporting to Finance. Calendar needs a **clean feeder map**, a publish-time assembly, that is deterministic and boring.

What I’d lock next is not code, but the **field-to-source catalog** and the **publish assembly pipeline**.

# Suggested feeder pipeline in Calendar

At publish time, Calendar should do this in order:

1. **Load demand + project facts**
   
   - demand row
   
   - project row
   
   - funding plan rows / project funding hints

2. **Derive planning context**
   
   - source profile hint
   
   - ops support planned
   
   - spending class
   
   - tags
   
   - project/demand display values

3. **Ask Governance for the applied semantics**
   
   - eligible fund keys
   
   - default restriction keys
   
   - source profile summary
   
   - decision fingerprint

4. **Derive workflow cues**
   
   - receive posture
   
   - reserve expectation
   
   - reimbursement expectation
   
   - bridge support possible
   
   - return-unused posture
   
   - recommended income kind
   
   - allowed realization modes

5. **Assemble full `FundingDemandContextDTO` snapshot**
   
   - `schema_version`
   
   - `demand`
   
   - `planning`
   
   - `policy`
   
   - `workflow`

6. **Validate the packet**
   
   - all required fields present
   
   - JSON shape correct
   
   - tuple/list normalization done
   
   - no live-policy lookups needed after this point

7. **Persist whole blob**
   
   - write `published_context_json`
   
   - never patch pieces in place

That is the Calendar feeder story in plain English.

# Field catalog for feeder design

## 1) `demand` section

These are mostly easy feeders.

| Field                 | Required v1         | Source in Calendar        | Freeze rule        | Trust               |
| --------------------- | ------------------- | ------------------------- | ------------------ | ------------------- |
| `funding_demand_ulid` | yes                 | demand row                | frozen             | authoritative       |
| `project_ulid`        | yes                 | demand row                | frozen             | authoritative       |
| `title`               | yes                 | demand row at publish     | frozen             | descriptive         |
| `status`              | yes                 | publish-time status       | frozen in snapshot | descriptive/history |
| `goal_cents`          | yes                 | demand row at publish     | frozen             | authoritative       |
| `deadline_date`       | yes, nullable value | demand row at publish     | frozen             | operational         |
| `published_at_utc`    | yes                 | publish service timestamp | frozen             | authoritative       |

### Feeder note

Even though some of these also live on the row later, the snapshot should still carry them because you want a **complete publish packet**.

---

## 2) `planning` section

This is where the real feeder work starts.

| Field                 | Required v1                                | Source                              | Freeze rule | Trust         |
| --------------------- | ------------------------------------------ | ----------------------------------- | ----------- | ------------- |
| `project_title`       | yes                                        | project row at publish              | frozen      | descriptive   |
| `spending_class`      | yes                                        | demand row / demand prep state      | frozen      | authoritative |
| `tag_any`             | yes                                        | demand row / normalized tags        | frozen      | authoritative |
| `source_profile_key`  | yes, nullable only if truly absent         | project funding-plan hint rollup    | frozen      | authoritative |
| `ops_support_planned` | yes, nullable bool allowed only if unknown | project funding-plan hint rollup    | frozen      | authoritative |
| `planning_basis`      | yes                                        | constant/enum from Calendar builder | frozen      | diagnostic    |

### Feeder note

From the bundle, these are the main fields that are currently too “live-derived” to leave floating:

- `source_profile_key`

- `ops_support_planned`

Those must be captured into the snapshot at publish.

---

## 3) `policy` section

This is the Governance-fed section Calendar freezes.

| Field                      | Required v1 | Source                                     | Freeze rule | Trust                    |
| -------------------------- | ----------- | ------------------------------------------ | ----------- | ------------------------ |
| `decision_fingerprint`     | yes         | Governance preview result                  | frozen      | authoritative/diagnostic |
| `eligible_fund_keys`       | yes         | Governance selector result                 | frozen      | authoritative            |
| `default_restriction_keys` | yes         | Governance source-profile / selector merge | frozen      | authoritative            |
| `source_profile_summary`   | yes         | Governance summary builder                 | frozen      | authoritative            |

### `source_profile_summary`

| Field                        | Required v1 | Source     | Freeze rule | Trust         |
| ---------------------------- | ----------- | ---------- | ----------- | ------------- |
| `key`                        | yes         | Governance | frozen      | authoritative |
| `source_kind`                | yes         | Governance | frozen      | authoritative |
| `support_mode`               | yes         | Governance | frozen      | authoritative |
| `approval_posture`           | yes         | Governance | frozen      | authoritative |
| `default_restriction_keys`   | yes         | Governance | frozen      | authoritative |
| `bridge_allowed`             | yes         | Governance | frozen      | authoritative |
| `repayment_expectation`      | yes         | Governance | frozen      | authoritative |
| `forgiveness_rule`           | yes         | Governance | frozen      | authoritative |
| `auto_ops_bridge_on_publish` | yes         | Governance | frozen      | authoritative |

### Feeder note

Calendar should not invent this section. It should ask Governance for a **summary DTO**, then freeze that into the snapshot.

---

## 4) `workflow` section

This is the interpretation layer. Very useful, but a few values can start nullable if needed.

| Field                         | Required section / field        | Source                                                   | Freeze rule | Trust                 |
| ----------------------------- | ------------------------------- | -------------------------------------------------------- | ----------- | --------------------- |
| `receive_posture`             | yes / nullable value okay       | Calendar interpretation of planning + Governance summary | frozen      | advisory-to-strong    |
| `reserve_on_receive_expected` | yes / nullable okay             | Governance/Finance-informed rule mapping                 | frozen      | advisory              |
| `reimbursement_expected`      | yes / nullable okay             | Governance/source-profile posture                        | frozen      | authoritative context |
| `bridge_support_possible`     | yes / nullable okay             | Governance summary (`bridge_allowed`) + ops posture      | frozen      | authoritative context |
| `return_unused_posture`       | yes / nullable okay             | Governance/source-profile posture                        | frozen      | authoritative context |
| `recommended_income_kind`     | yes / nullable okay             | Governance/Finance selector bridge                       | frozen      | advisory              |
| `allowed_realization_modes`   | yes / nullable empty tuple okay | Calendar interpretation from source-profile posture      | frozen      | advisory-to-guardrail |

### Feeder note

I would require the **section** in v1, but allow a few fields to be nullable while the rule-set matures.

# Feeder ownership by helper

Without naming code yet, I’d split the builder mentally into four helpers:

## A. Demand snapshot feeder

Builds:

- `funding_demand_ulid`

- `project_ulid`

- `title`

- `status`

- `goal_cents`

- `deadline_date`

- `published_at_utc`

## B. Planning snapshot feeder

Builds:

- `project_title`

- `spending_class`

- `tag_any`

- `source_profile_key`

- `ops_support_planned`

- `planning_basis`

This one reads project + funding plan state.

## C. Policy snapshot feeder

Builds:

- `decision_fingerprint`

- `eligible_fund_keys`

- `default_restriction_keys`

- `source_profile_summary`

This one calls Governance.

## D. Workflow cue feeder

Builds:

- `receive_posture`

- `reserve_on_receive_expected`

- `reimbursement_expected`

- `bridge_support_possible`

- `return_unused_posture`

- `recommended_income_kind`

- `allowed_realization_modes`

This one should be deterministic and boring. It should not reach back into raw policy files. It should interpret the already-resolved planning + policy snapshots.

# Two contract expectations I’d pin for the feeders

## 1) Feeders must be pure assembly logic

The publish builder should gather inputs, derive the packet, validate it, and store it. It should not embed ad hoc route/UI logic.

## 2) Feeders must fail loudly on incomplete publish context

If publish-time data is not sufficient to build the snapshot, publish should fail rather than create a half-baked packet.

That means especially:

- missing `source_profile_key`

- malformed source profile summary

- missing eligible fund keys when policy expects them

- malformed tag normalization

- missing decision fingerprint

## My practical recommendation

Before writing code, I’d make one short design note in the thread or repo with three sections:

1. **DTO field catalog**

2. **feeder source map**

3. **nullable-by-design workflow fields**

That will make the Calendar publish work much cleaner and will save us from hand-waving when we turn back to Sponsors.

---

# Anti-drift rules

### 1) One builder, one shape

There should be exactly one Calendar service that assembles `FundingDemandContextDTO` and its JSON payload.

No route-level assembly.  
No Sponsor-side reconstruction.  
No Finance-side reinterpretation.

Everything downstream reads the same frozen packet.

### 2) DTO first, JSON second

Build the typed DTO first, then serialize that DTO into `published_context_json`.

Not the other way around.

That gives you:

- one canonical field set,

- one canonical normalization path,

- one place to validate required vs nullable fields.

### 3) Governance feeds policy, not raw JSON

Calendar should never hand-pick fields out of Governance policy JSON during snapshot assembly.

Instead, Calendar should call Governance helpers/contracts that return already-resolved values like:

- `eligible_fund_keys`

- `default_restriction_keys`

- `source_profile_summary`

- `decision_fingerprint`

That prevents Calendar from becoming a shadow policy interpreter.

### 4) Workflow cues derive only from frozen inputs

The `workflow` section should be derived only from:

- frozen planning inputs,

- frozen policy inputs,

- stable mapping logic in Calendar.

It should not do fresh policy lookups after the policy snapshot is resolved.

That way, if policy changes later, the workflow section does not silently drift.

### 5) No partial writes

`published_context_json` gets replaced whole or not at all.

Never patch:

- just one cue,

- just one policy field,

- just the demand title,

- just the source profile summary.

That is where subtle drift creeps in.

### 6) Publish fails hard on incomplete context

If Calendar cannot build a complete, valid snapshot, publish should fail.

Especially if missing:

- `source_profile_key`

- `decision_fingerprint`

- `eligible_fund_keys`

- `source_profile_summary`

- normalized `tag_any`

- required demand metadata

No “best effort” publish packets.

## Drift vectors to guard against

These are the likely trouble spots.

### Live Funding Plan re-reads

Today some desired fields are derived from funding-plan rows. If those rows change after publish and you re-read them later, the packet drifts.

Fix: snapshot those publish-time derived values into `published_context_json`.

### Live Governance re-reads

If you rebuild `source_profile_summary` from current policy later, the packet drifts.

Fix: store the fully resolved summary in the snapshot.

### Duplicate mapping logic

If Calendar, Sponsors, and Finance each infer `receive_posture` or `allowed_realization_modes` their own way, semantics drift.

Fix: derive once in Calendar, consume everywhere else.

### Normalization drift

Things like:

- tuple vs list

- tag ordering

- default restriction ordering

- empty vs null

can create noisy diffs and odd bugs.

Fix: normalize all collections in one place before DTO serialization.

## Practical controls

I’d put these in place conceptually before code.

### Canonical builder stages

Use a fixed assembly sequence:

1. demand snapshot

2. planning snapshot

3. policy snapshot

4. workflow cues

5. validate

6. persist

No shortcuts.

### Canonical normalization rules

For every collection field:

- store as JSON arrays

- sort where order is not semantically meaningful

- de-duplicate before storing

- use `[]` instead of null where “empty collection” is the real meaning

Examples:

- `tag_any`

- `eligible_fund_keys`

- `default_restriction_keys`

- `allowed_realization_modes`

### Schema versioning

Always include:

- `schema_version`

That gives you controlled evolution later.

### Snapshot validation

Before writing the blob, validate:

- required sections exist

- required scalar fields are present

- booleans are booleans

- arrays are arrays

- no unexpected top-level shape drift

This can be lightweight at first, but it should exist.

## The cleanest mental model

Think of publish as producing two things:

### 1) operational state change

The demand becomes published.

### 2) sealed context packet

The demand gets its frozen funding context envelope.

Both happen together, or neither happens.

That keeps the system honest.

## What I’d pin as the feeder doctrine

Here’s the short version:

**Calendar publishes one sealed, versioned funding context packet. Governance supplies resolved semantics into that packet. Sponsors and Finance consume the packet as-is. No downstream slice rebuilds or reinterprets the packet from live policy or live planning data.**

---

Here’s the workflow cue derivation mapping I’d pin for `FundingDemandContextDTO.workflow`.

This assumes the cue builder runs **after** `planning` and `policy` are already frozen, and derives cues only from those frozen inputs.

# Workflow cue derivation mapping

| Cue                           | Inputs                                                                                                                                            | Derivation rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Fallback / failure rule                                                                          | Trust                 |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------- |
| `receive_posture`             | `policy.source_profile_summary.source_kind`, `policy.source_profile_summary.support_mode`                                                         | Map the publish snapshot to the primary funding posture: `cash_support + direct_cash -> direct_support`; `cash_support + restricted_grant_cash -> direct_support`; `reimbursement_support + reimbursement_promise -> reimbursement_expected`; `in_kind_support + in_kind_offset -> in_kind_offset`; `operations_support + ops_seed -> ops_seed`; `operations_support + ops_backfill -> ops_backfill`; `operations_support + ops_bridge -> ops_bridge`                                                    | If `source_profile_summary` is missing, publish fails. If combination is unknown, publish fails. | strong                |
| `reserve_on_receive_expected` | `receive_posture`, `policy.source_profile_summary.source_kind`, `policy.source_profile_summary.support_mode`                                      | `true` for direct cash support and restricted grant cash, because realized money normally lands in Finance then gets reserved to the demand. `false` for `in_kind_offset`. `false` for `reimbursement_expected` because reimbursement is generally after-the-fact receipt, not initial demand funding. `false` for pure ops support modes unless a later explicit rule says otherwise.                                                                                                                   | Unknown posture -> `null` only if you want a soft v1; my preference is fail on unknown posture.  | advisory              |
| `reimbursement_expected`      | `policy.source_profile_summary.reimbursement_expected`, `policy.source_profile_summary.source_kind`, `policy.source_profile_summary.support_mode` | Primary rule: use the source profile boolean. Secondary sanity check: if `source_kind == reimbursement_support` or `support_mode == reimbursement_promise`, this should be `true`.                                                                                                                                                                                                                                                                                                                       | If the boolean conflicts with the semantic shape, publish fails.                                 | authoritative context |
| `bridge_support_possible`     | `policy.source_profile_summary.bridge_allowed`, `planning.ops_support_planned`, `policy.source_profile_summary.support_mode`                      | Primary rule: use `bridge_allowed`. Secondary note: if `support_mode == ops_bridge`, this must also be `true`. `ops_support_planned` does not make bridge possible by itself; it only tells you whether bridge/ops support was contemplated.                                                                                                                                                                                                                                                             | If `support_mode == ops_bridge` and `bridge_allowed == false`, publish fails.                    | authoritative context |
| `return_unused_posture`       | `policy.source_profile_summary.return_unused_rule`                                                                                                | Direct passthrough from source profile summary. Suggested normalized values stay exactly aligned to Governance: `return_to_source`, `retain_for_same_restriction_scope`, `return_to_operations`, `repay_to_operations`, `not_applicable`                                                                                                                                                                                                                                                                 | Missing rule -> publish fails.                                                                   | authoritative context |
| `recommended_income_kind`     | `policy.source_profile_summary.source_kind`, `policy.source_profile_summary.support_mode`                                                         | Map to canonical Finance income kind: `direct_cash -> donation`; `restricted_grant_cash -> grant_disbursement`; `reimbursement_promise -> reimbursement`; `in_kind_offset -> inkind`; ops support modes default to `other` unless you later formalize a better mapping.                                                                                                                                                                                                                                  | Unknown combo -> `null` allowed in v1, but I’d rather fail than guess.                           | advisory              |
| `allowed_realization_modes`   | `receive_posture`, `policy.source_profile_summary.source_kind`, `policy.source_profile_summary.support_mode`                                      | Produce the allowed downstream realization paths as a normalized list. Recommended baseline: `direct_support -> ["pledge","donation"]`; `reimbursement_expected -> ["pledge","reimbursement_receipt"]`; `in_kind_offset -> ["donation"]` or later `["inkind_commitment"]` if you formalize it; `ops_seed -> ["pledge"]`; `ops_backfill -> ["pledge"]`; `ops_bridge -> ["pledge","reimbursement_receipt"]`. Do **not** include `pass_through` unless the source profile explicitly supports that posture. | Unknown posture -> publish fails. Empty list is not valid.                                       | guardrail/advisory    |

---

# Canonical derivation rules

## 1) `receive_posture` is the anchor cue

This is the root interpretation. The rest of the workflow section should mostly flow from it.

Suggested canonical values:

- `direct_support`

- `reimbursement_expected`

- `in_kind_offset`

- `ops_seed`

- `ops_backfill`

- `ops_bridge`

I would not overload this field with UI wording. Keep it semantic.

## 2) `reimbursement_expected` comes from source-profile semantics, not guesswork

Because the policy file already has an explicit boolean, this cue should not be “inferred loosely.” It should be frozen from the source profile and only sanity-checked against `source_kind` / `support_mode`.

## 3) `bridge_support_possible` is about policy permission, not planning desire

`ops_support_planned` tells you whether the project expected/support-planned operational help.  
It does **not** tell you that bridge is allowed.

So:

- `bridge_allowed` answers “may this happen?”

- `ops_support_planned` answers “was this contemplated/planned?”

Both matter, but they are not the same.

## 4) `recommended_income_kind` should stay advisory

This field is useful for Sponsors and Finance handoff, but Finance still owns the final posting truth. So this cue should be used for defaults and validation context, not as the sole source of posting decisions.

## 5) `allowed_realization_modes` should be a contract list, not just a mirror of today’s Sponsor enums

Today Sponsors has intent kinds:

- `pledge`

- `donation`

- `pass_through`

But the workflow contract you are designing is broader than the current implementation. So I would let the context DTO speak in the fuller downstream language now, even if Sponsors initially only consumes a subset.

That means values like:

- `reimbursement_receipt`

- later maybe `inkind_commitment`

are valid as workflow cues even if current Sponsor forms/services do not yet expose them.

---

# Recommended normalization rules

Use these in the Calendar builder so the packet is stable:

- `allowed_realization_modes` is always a sorted, de-duplicated JSON array.

- `receive_posture`, `return_unused_posture`, and `recommended_income_kind` are lower-case canonical keys.

- Never store empty strings.

- Use `null` only when the field is explicitly allowed nullable in v1.

- Prefer publish failure over storing an ambiguous cue.

---

# Current policy-profile mapping

Based on the uploaded `funding_source_controls` policy, this is the practical mapping I’d pin right now.

| Source profile key                       | `receive_posture`        | `reserve_on_receive_expected` | `reimbursement_expected` | `bridge_support_possible` | `return_unused_posture`             | `recommended_income_kind` | `allowed_realization_modes`          |
| ---------------------------------------- | ------------------------ | ----------------------------- | ------------------------ | ------------------------- | ----------------------------------- | ------------------------- | ------------------------------------ |
| `mission_local_veterans_cash`            | `direct_support`         | true                          | false                    | false                     | `retain_for_same_restriction_scope` | `donation`                | `["donation","pledge"]`              |
| `welcome_home_reimbursement_bridgeable`  | `reimbursement_expected` | false                         | true                     | true                      | `not_applicable`                    | `reimbursement`           | `["pledge","reimbursement_receipt"]` |
| `restricted_project_grant_return_unused` | `direct_support`         | true                          | false                    | false                     | `return_to_source`                  | `grant_disbursement`      | `["donation","pledge"]`              |
| `inkind_project_offset`                  | `in_kind_offset`         | false                         | false                    | false                     | `not_applicable`                    | `inkind`                  | `["donation"]`                       |
| `ops_seed_board_motion`                  | `ops_seed`               | false                         | false                    | false                     | `return_to_operations`              | `other`                   | `["pledge"]`                         |
| `ops_backfill_board_motion`              | `ops_backfill`           | false                         | false                    | false                     | `return_to_operations`              | `other`                   | `["pledge"]`                         |
| `ops_bridge_preapproved`                 | `ops_bridge`             | false                         | true                     | true                      | `repay_to_operations`               | `other`                   | `["pledge","reimbursement_receipt"]` |

---

# Two rules I would pin hard

## Hard rule 1

If `source_profile_summary` is missing or semantically inconsistent, **publish fails**.

No half-built workflow section.

## Hard rule 2

The workflow section is derived **once** in Calendar and then frozen into `published_context_json`.

Sponsors and Finance consume it. They do not recalculate it.

---

# One refinement I’d make now

I would add a tiny internal note to the design:

**`allowed_realization_modes` describes permitted fulfillment pathways, not necessarily the exact current Sponsor form enum.**

That gives you room to:

- keep today’s Sponsors slice narrow for a moment,

- while still designing the context packet correctly.

---

# Builder Spec

Here’s the builder spec I’d pin for Calendar.

The goal is to make publish-time context assembly:

- deterministic,

- slice-correct,

- easy to test,

- and impossible for Sponsors or Finance to reinterpret differently later.

# Calendar publish builder spec

## High-level shape

One orchestration service owns the publish act.

It calls four subordinate builders in order:

1. `build_demand_snapshot(...)`

2. `build_planning_snapshot(...)`

3. `build_policy_snapshot(...)`

4. `build_workflow_cues(...)`

Then it assembles and validates the final packet:

5. `assemble_funding_demand_context(...)`

6. `validate_funding_demand_context(...)`

7. `persist_published_context(...)`

That gives you one lawful assembly path.

---

# Top-level orchestration service

## Purpose

Publish a funding demand and seal its immutable context packet.

## Conceptual signature

```python
publish_funding_demand(
    funding_demand_ulid: str,
    actor_ulid: str,
) -> FundingDemandContextDTO
```

## Responsibilities

- load the demand aggregate

- assert the demand is publishable

- build the full context packet

- validate it

- store it on `FundingDemand.published_context_json`

- update live demand publish fields

- emit the appropriate Calendar/Ledger event

- return the DTO

## Inputs it needs

From Calendar:

- demand row

- project row

- project funding plan rows / project funding hint inputs

From Governance:

- resolved finance semantics

- source profile summary

- decision fingerprint

- eligible funds

- default restriction keys

From system state:

- publish timestamp

- actor ULID

## Publish preconditions

This service should fail if any of these are not true:

- demand exists

- demand is in a publishable state

- project exists

- spending class is available

- tags are normalized

- source profile can be resolved

- Governance semantics resolve cleanly

- final DTO validates

That keeps “published” meaningful.

---

# Builder 1 — demand snapshot

## Purpose

Capture the demand itself as it exists at publish time.

## Conceptual signature

```python
build_demand_snapshot(
    demand_row,
    *,
    published_at_utc: str,
) -> FundingDemandPublishedSnapshotDTO
```

## Reads

From `FundingDemand`:

- `ulid`

- `project_ulid`

- `title`

- `status`

- `goal_cents`

- `deadline_date`

From the publish service:

- `published_at_utc`

## Returns

```python
FundingDemandPublishedSnapshotDTO(
    funding_demand_ulid=...,
    project_ulid=...,
    title=...,
    status="published",
    goal_cents=...,
    deadline_date=...,
    published_at_utc=...,
)
```

## Rules

- `status` in the snapshot reflects the status at the moment of publish

- this builder should not inspect Governance

- no policy interpretation here

- this is pure Calendar demand capture

## Failures

Fail if:

- title missing

- goal invalid

- demand/project linkage invalid

---

# Builder 2 — planning snapshot

## Purpose

Capture the Calendar-owned operational context behind the demand.

## Conceptual signature

```python
build_planning_snapshot(
    demand_row,
    project_row,
    funding_plan_rows,
) -> FundingDemandPlanningSnapshotDTO
```

## Reads

From project:

- project title

From demand:

- spending class

- tag set / `tag_any`

From project funding plan / project hint logic:

- `source_profile_key`

- `ops_support_planned`

Derived by Calendar:

- `planning_basis`

## Returns

```python
FundingDemandPlanningSnapshotDTO(
    project_title=...,
    spending_class=...,
    tag_any=(...),
    source_profile_key=...,
    ops_support_planned=...,
    planning_basis="funding_plan_rows",
)
```

## Rules

- normalize `tag_any` here

- resolve `source_profile_key` here

- resolve `ops_support_planned` here

- this is the last place those values are allowed to be “live-derived”

Once this builder returns, those values become frozen.

## Failures

Fail if:

- project title unavailable

- spending class missing

- tags malformed

- source profile cannot be resolved

- ops support posture cannot be resolved when policy requires it

---

# Builder 3 — policy snapshot

## Purpose

Ask Governance for the publish-time authorized semantics package.

## Conceptual signature

```python
build_policy_snapshot(
    demand_snapshot: FundingDemandPublishedSnapshotDTO,
    planning_snapshot: FundingDemandPlanningSnapshotDTO,
) -> FundingDemandPolicySnapshotDTO
```

## Reads

From frozen inputs:

- demand snapshot

- planning snapshot

From Governance helpers/contracts:

- decision fingerprint

- eligible fund keys

- default restriction keys

- source profile summary

## Returns

```python
FundingDemandPolicySnapshotDTO(
    decision_fingerprint=...,
    eligible_fund_keys=(...),
    default_restriction_keys=(...),
    source_profile_summary=FundingSourceProfileSummaryDTO(...),
)
```

## Governance call posture

Calendar should not parse policy JSON directly here.

Instead it should call a small number of resolved helpers, conceptually like:

- resolve eligible funds

- resolve restriction defaults

- build source profile summary

- compute decision fingerprint

## Rules

- all returned collections normalized here

- source profile summary must be fully resolved here

- this builder returns only frozen, publish-time policy outputs

## Failures

Fail if:

- source profile summary missing

- eligible fund list missing or invalid

- decision fingerprint missing

- Governance results are inconsistent

---

# Builder 4 — workflow cues

## Purpose

Interpret the frozen planning + policy snapshots into downstream handling cues.

## Conceptual signature

```python
build_workflow_cues(
    planning_snapshot: FundingDemandPlanningSnapshotDTO,
    policy_snapshot: FundingDemandPolicySnapshotDTO,
) -> FundingDemandWorkflowCuesDTO
```

## Reads

From planning:

- `source_profile_key`

- `ops_support_planned`

- maybe `spending_class` if later needed

From policy:

- full `source_profile_summary`

- default restrictions

- eligible funds

- decision fingerprint only if needed for diagnostics

## Returns

```python
FundingDemandWorkflowCuesDTO(
    receive_posture=...,
    reserve_on_receive_expected=...,
    reimbursement_expected=...,
    bridge_support_possible=...,
    return_unused_posture=...,
    recommended_income_kind=...,
    allowed_realization_modes=(...),
)
```

## Rules

This builder uses the derivation table we just pinned.

Important constraints:

- it must not re-read live policy

- it must not inspect Sponsors

- it must not inspect Finance posting rows

- it is interpretation only, based on frozen inputs

## Failures

Fail if:

- source profile summary missing

- posture combination unknown

- allowed realization modes would be empty

- rule contradiction appears, such as `ops_bridge` with `bridge_allowed=false`

---

# Builder 5 — assembly

## Purpose

Create the final packet.

## Conceptual signature

```python
assemble_funding_demand_context(
    demand_snapshot: FundingDemandPublishedSnapshotDTO,
    planning_snapshot: FundingDemandPlanningSnapshotDTO,
    policy_snapshot: FundingDemandPolicySnapshotDTO,
    workflow_cues: FundingDemandWorkflowCuesDTO,
) -> FundingDemandContextDTO
```

## Returns

```python
FundingDemandContextDTO(
    schema_version=1,
    demand=demand_snapshot,
    planning=planning_snapshot,
    policy=policy_snapshot,
    workflow=workflow_cues,
)
```

## Rules

- this builder contains no new logic

- it only composes

- schema version is set here

- this should be pure and boring

---

# Builder 6 — validation

## Purpose

Assert the packet is complete, coherent, and serializable.

## Conceptual signature

```python
validate_funding_demand_context(
    context: FundingDemandContextDTO,
) -> None
```

## Checks

### Structural checks

- schema version present

- all four sections present

- no wrong top-level shape

### Required field checks

- all required v1 fields present

- nullable fields are only null where allowed

### Normalization checks

- arrays/lists normalized

- no duplicate fund keys

- no duplicate realization modes

- no empty strings

### Semantic checks

- workflow cues consistent with source profile summary

- reimbursement posture consistent with source profile

- bridge posture consistent with source profile

- return-unused posture present

### Serialization checks

- DTO can be converted to JSON object

- top-level result is object-like, not list-like

## Failure posture

Any validation failure aborts publish.

---

# Builder 7 — persistence

## Purpose

Store the frozen packet and finalize publish state.

## Conceptual signature

```python
persist_published_context(
    demand_row,
    context: FundingDemandContextDTO,
    *,
    actor_ulid: str,
    published_at_utc: str,
) -> None
```

## Writes

To `FundingDemand`:

- `published_context_json`

- `status = "published"` or live publish status

- `published_at_utc`

Optionally keep existing explicit columns in sync if they still exist:

- `eligible_fund_keys_json`

- `decision_fingerprint`

- other publish-support fields already on the model

## Rules

- store the full packet, not fragments

- replace whole blob

- no partial updates

- write happens in same transaction as publish state change

## Event side-effects

Emit a single publish event that includes references such as:

- demand ULID

- project ULID

- actor ULID

- decision fingerprint

- maybe snapshot schema version

No PII.

---

# Read-side companion service

Once this exists, Calendar also needs a read-side accessor.

## Conceptual signature

```python
get_funding_demand_context(
    funding_demand_ulid: str,
) -> FundingDemandContextDTO
```

## Behavior

- load demand row

- ensure `published_context_json` exists

- validate or parse JSON into DTO

- return DTO

## Failure modes

- not found -> `not_found`

- row exists, blob missing -> `not_published` / `bad_state`

- blob malformed -> `data_integrity_error`

That becomes the clean contract read for Sponsors.

---

# De-publish / re-publish behavior

## De-publish

Do not clear `published_context_json` by default.

Reason:

- diagnostics

- audit explanation

- comparison before revision

But de-published demands should no longer appear in “open opportunities.”

## Re-publish

Run the full builder chain again.

Do not patch the old blob.  
Replace it wholesale with a new frozen packet.

That gives you:

- stable old packet until republish

- deterministic new packet after republish

---

# Suggested internal service layering

To fit your architecture, I’d keep it like this:

## Route

Thin:

- parse ULID

- call publish service

- flash/redirect/respond

## Calendar service

Owns orchestration:

- publish service

- de-publish service

- read service

## Calendar helper/builders

Pure-ish builder functions:

- demand snapshot

- planning snapshot

- policy snapshot

- workflow cue builder

- validator

- serializer/parser

## Governance helpers/contracts

Read-only semantics providers:

- eligible funds

- source profile summary

- default restriction keys

- decision fingerprint

That is very much in line with your slice rules.

---

# Why this helps Sponsors CRM later

This builder spec quietly gives Sponsors a very strong footing.

Because once `get_funding_demand_context(...)` exists, Sponsors CRM can grow around a stable opportunity packet that already includes:

- the need

- the planning posture

- the approved source semantics

- the suggested realization posture

That means future Sponsor CRM features can key off a real “funding opportunity context” rather than trying to reverse-engineer need from raw Calendar and Governance state.

That is the beginning of a sane sponsor matching surface.

Not full CRM yet, but definitely the right substrate for it.

---

# The short doctrine

If I had to pin the builder philosophy in one paragraph:

**Calendar publish assembles one sealed funding context packet from demand facts, planning facts, and Governance-resolved semantics. That packet is validated, stored whole on `FundingDemand.published_context_json`, and exposed by `calendar_v2` for downstream use. Sponsors and Finance consume the packet; they do not rebuild it.**

The next useful thing I’d draft is a **service-responsibility map for Sponsors** showing exactly where this new Calendar context read plugs into opportunity reads, commitment creation, and realization flow.

---

Exactly. The contract gives you the **artifact**. Sponsors still needs the **behavior model** around that artifact.

The missing piece is to define where `FundingDemandContextDTO` sits inside Sponsors slice so it becomes the spine of sponsor-opportunity work instead of just “more data available somewhere.”

## The right mental model

Inside Sponsors, this DTO should act as the **opportunity context packet**.

That means Sponsors should stop thinking in terms of:

“there is a demand with a title and a goal”

and start thinking in terms of:

“there is a published funding opportunity with a frozen operational context, policy posture, and fulfillment cues.”

That is a much more CRM-friendly object.

## How Sponsors should use it

I’d break Sponsors usage into three layers.

### 1. Opportunity discovery

This is the read side.

Sponsors should use the thin demand list to find candidate opportunities, then use `FundingDemandContextDTO` when the user drills into one.

That detail view should answer questions like:

- What is this need really for?

- Is it direct support, reimbursement-backed, or ops-bridge shaped?

- Which fund postures are valid?

- What realization paths are expected?

- What restrictions or return-unused posture matter?

That turns the DTO into a real sponsor-matching aid.

### 2. Commitment / intent creation

When a sponsor expresses interest, Sponsors should capture that as a Sponsor-owned record, but the intent should be created **in the context of the DTO**.

So the commitment flow should read the context packet and use it to shape:

- what kinds of commitments are allowed,

- what default funding mode makes sense,

- what warnings or notes the user should see,

- what Sponsor-side follow-up is likely needed.

This is where the CRM side begins to get teeth.

### 3. Realization / Finance handoff

When a commitment becomes real money or support, Sponsors should use the DTO to guide the handoff into Finance.

Not to replace Finance truth, but to provide:

- the correct demand linkage,

- the publish-time policy posture,

- the expected receive mode,

- the likely income-kind default,

- reserve expectation,

- reimbursement or bridge context.

That is where the cascade tightens up.

## Sponsors service-responsibility map

Here’s the split I’d recommend.

### Sponsors read services

These are opportunity-facing.

`list_funding_opportunities(...)`  
returns the thin list for browsing.

`get_funding_opportunity_detail(demand_ulid)`  
should combine:

- thin demand/opportunity facts,

- `FundingDemandContextDTO`,

- current Sponsor activity against that demand,

- maybe current Finance totals later.

This becomes the core read model for the Sponsorship UI.

### Sponsors CRM services

These are relationship-facing.

`create_funding_intent(...)`  
should:

- load `FundingDemandContextDTO`,

- validate the opportunity is currently actionable,

- shape the intent according to workflow cues,

- store Sponsor-side commitment metadata.

Later CRM growth can hang here:

- outreach state,

- sponsorship stage,

- warm lead vs committed support,

- next action,

- relationship notes,

- confidence/probability.

That is probably the natural next CRM layer after this funding-demand work.

### Sponsors realization services

These are execution-facing.

`preview_intent_realization(...)`  
should:

- read the context packet,

- validate that the chosen pathway fits the published posture,

- derive default Finance handoff parameters,

- show what will happen.

`commit_intent_realization(...)`  
should:

- post into Finance,

- reserve if appropriate,

- update Sponsor intent state,

- emit Sponsor/Ledger events.

This keeps Sponsors as an orchestrator, not a money ledger.

## What the DTO should influence in Sponsors

The most important practical point is this:

The DTO should not just be displayed.  
It should actively drive behavior.

I’d have it influence at least these things:

### Opportunity classification

Sponsors can bucket opportunities by context:

- direct sponsorship opportunities

- reimbursement-backed opportunities

- ops-support opportunities

- in-kind offset opportunities

That is useful for sponsor matching and later CRM segmentation.

### Allowed commitment pathways

The workflow cues should constrain which intent/realization pathways Sponsors offers.

### Suggested ask posture

The context packet can tell Sponsors whether this is a:

- grant-style ask,

- reimbursement-style ask,

- operations-support ask,

- in-kind offset ask.

That is the beginning of a real sponsor strategy layer.

### Finance handoff defaults

The packet should guide, not dictate:

- recommended income kind,

- reserve expectation,

- restrictions posture,

- demand linkage.

## The CRM angle

You’re right to feel that this is foundational to the CRM portion.

A proper Sponsor CRM is not just “a sponsor table with contacts.” It needs three things:

- **who the sponsor is**

- **what kinds of opportunities fit them**

- **what stage each opportunity relationship is in**

You already have the first one in Entity/POC relationships.  
`FundingDemandContextDTO` helps create the second one.  
Then Sponsor intents/commitments give you the third one.

That is why this work matters so much. It creates the “opportunity object” that real CRM behavior can attach to.

## Finance revisit

Yes, Finance should absolutely get a second pass after this.

But the order matters.

First:

- finalize the Calendar context packet,

- wire Sponsors to consume it properly.

Then:

- revisit Finance to ensure it accepts and uses the packet consistently for validation, traceability, and reporting context.

That order is better because Finance should consume a **stable contract**, not a moving target.

## The next best design step

The cleanest next move is to draft a **Sponsors service-responsibility map** around three flows:

- opportunity detail read

- funding intent creation

- intent realization preview/commit

and for each one, specify:

- what it reads from `calendar_v2`,

- what it owns in Sponsors,

- what it hands off to Finance,

- and what Ledger event should result.

That would make the practical use of this DTO inside Sponsors very concrete.

---

**Calendar slice is the right first target**.

The key thing is to keep the first implementation narrow and disciplined so you do not accidentally start solving Sponsors CRM and Finance integration all at once.

I’d attack it in this order:

1. **Calendar model + migration**  
   Add `published_context_json` to `FundingDemand`, generate the migration, and upgrade.  
   At the same time, decide one small rule now: existing publish-support fields like `eligible_fund_keys_json` and `decision_fingerprint` remain in place for now and stay synchronized during publish. That keeps the cutover gentle.

2. **Calendar DTOs and JSON helpers**  
   Create the dataclasses for:
   
   - `FundingDemandContextDTO`
   
   - `FundingDemandPublishedSnapshotDTO`
   
   - `FundingDemandPlanningSnapshotDTO`
   
   - `FundingDemandPolicySnapshotDTO`
   
   - `FundingDemandWorkflowCuesDTO`
   
   - `FundingSourceProfileSummaryDTO`

  Then add one serializer and one parser.  
  Build typed DTO first, then serialize to JSON. Read JSON, then parse back to DTO. That is your anti-drift backbone.

3. **Calendar builder pipeline**  
   Implement the pure builder helpers we pinned:
   
   - `build_demand_snapshot(...)`
   
   - `build_planning_snapshot(...)`
   
   - `build_policy_snapshot(...)`
   
   - `build_workflow_cues(...)`
   
   - `assemble_funding_demand_context(...)`
   
   - `validate_funding_demand_context(...)`

  This is the heart of the work.

4. **Wire publish / republish path**  
   Update Calendar publish logic so publish:
   
   - builds the packet,
   
   - validates it,
   
   - stores it whole in `published_context_json`,
   
   - keeps existing publish fields in sync,
   
   - emits the normal event/ledger side-effect.

  De-publish should leave the blob in place.

5. **Expose it through `calendar_v2`**  
   Add the dedicated read:
   
   - `get_funding_demand_context(funding_demand_ulid)`

  That gives Sponsors a stable contract target before you touch Sponsors internals.

6. **Tests before Sponsors**  
   Add tests for:
   
   - builder outputs
   
   - malformed / missing publish context failure
   
   - publish writes full blob
   
   - re-publish replaces blob wholesale
   
   - de-publish retains blob
   
   - contract read returns the DTO cleanly

Only after that would I move into Sponsors.

The reason I like this order is simple: once Calendar can produce and publish a sealed packet, Sponsors becomes a consumer problem instead of a design problem. That is much easier to reason about.

The only caution flag I’d raise is this: do not let the first pass get pulled into a generalized “project planning overhaul.” Stay focused on **FundingDemand publish context** only. The task/project synthesis work is real, but it is later work.

The first concrete move should be the migration plus DTO/builder scaffolding, before any route or Sponsor changes.
