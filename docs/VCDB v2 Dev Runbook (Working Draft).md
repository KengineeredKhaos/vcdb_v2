# VCDB v2 Dev Runbook (Working Draft)

## Purpose

This runbook is the working notebook for development and testing trip wires, maintenance procedures, guardrails, and future-developer survival notes.

This is intentionally **not** polished canon yet.  
Its job is to capture:

- procedures that must not be lost

- places where slice boundaries can drift

- fragile chains of dependency

- repeatable recovery/check procedures

- implementation notes that future developers will need in order to avoid breaking automation

The goal is simple:

> Trip wires are a feature, not a bug, **if we document them clearly and early**.

---

## Ground Rules

- Keep entries short, explicit, and practical.

- Prefer checklists over essays.

- Capture the trip wire as soon as it is discovered.

- Do not wait for polish before documenting a hazard.

- If a procedure prevents silent breakage, it belongs here.

- If a rule later becomes canon, it can be promoted into Ethos / Rubric / formal docs.

---

## Working Sections

1. Finance semantic key chain

2. Governance policy maintenance

3. Calendar planning / Funding Demand trip wires

4. Sponsor fulfillment / realization trip wires

5. Finance posting / COA mapping trip wires

6. Ledger / audit visibility trip wires

7. Validation / drift-test procedures

8. Admin maintenance procedures

9. Diagnostics / dev portal notes

10. Parking lot

---

## Runbook Entry Template

### Title

**Why this matters**

**Trip wire**

**What can break**

**Required procedure**

**Validation / checks**

**Notes / follow-up**

---

## 1) Finance Semantic Key Chain

### Adding a new finance semantic key

**Why this matters**

Governance owns the finance vocabulary, but Finance owns how that vocabulary lands on the Chart of Accounts.  
A new semantic key can be valid policy while still breaking automated posting if Finance is not taught how to route it.

**Trip wire**

A developer adds or changes a semantic key such as `expense_kind` in Governance taxonomy and assumes the system now "knows what to do" with it.  
It does not.

**What can break**

- Calendar may begin hinting a new semantic key.

- Governance validation may pass.

- Finance posting may fail because `posting_map_v1.json` has no route for the new key.

- Automated COA selection can break silently unless validation catches the gap.

**Ownership chain**

- Governance owns the words.

- Calendar may hint the words.

- Finance owns where the words land.

- Posting services interpret; they do not invent vocabulary.

**Required procedure**

When adding, renaming, deprecating, or repurposing a finance semantic key:

1. Update `policy_finance_taxonomy.json`.

2. Validate the policy file against its schema.

3. Decide whether the new key is **postable now** or only reserved for future use.

4. If the key is postable, update `finance/data/posting_map_v1.json`.

5. Confirm `finance/services_semantics_posting.py` accepts and routes the key correctly.

6. Update any relevant `calendar/taxonomy.py` `finance_hints` entries.

7. Run policy validation and drift tests.

8. Run Finance semantic-posting tests.

9. Document the change in this runbook if there is any non-obvious consequence.

**Validation / checks**

Minimum checks:

- Every Calendar `finance_hints.expense_kinds[]` key must exist in Governance taxonomy.

- Every Finance posting-map key must exist in Governance taxonomy.

- Every Governance **postable** `expense_kind` must exist in `posting_map_v1.json`.

- `flask dev policy-health` must pass cleanly.

- Finance posting tests must pass cleanly.

**Boundary warnings**

Do not:

- put account codes in Governance policy

- invent finance aliases in Calendar taxonomy

- hard-code duplicate posting-map logic in posting services

- assume a valid policy key is automatically routable in Finance

**Notes / follow-up**

This procedure should eventually become a pinned maintenance checklist for Future Dev.

---

## 2) Governance Policy Maintenance

### Metadata block consistency

**Why this matters**

All Governance policy files should share one consistent metadata block shape so policy inventory, validation, and future admin tooling remain predictable.

**Trip wire**

Policies evolve with inconsistent `meta` fields, making schema validation and maintenance harder over time.

**Required procedure**

Each Governance policy JSON should carry the same required `meta` structure:

- `description`

- `effective_on`

- `notes`

- `policy_key`

- `schema_version`

- `status`

- `title`

- `version`

**Validation / checks**

- Schema validation must require the full `meta` block.

- `policy-health` should fail on malformed or incomplete metadata.

---

## 3) Parking Lot

- Document the exact procedure for adding a new finance semantic key end-to-end.

- Document Funding Plan revision behavior versus Finance factual history.

- Document the difference between sponsor return-unused, operations repayment, and project loss write-off.

- Document the source-profile chain from Calendar Funding Plan to Governance preview to Finance posting.

- Document drift tests between Governance taxonomy, Calendar finance hints, Finance posting map, and posting services.

---

## Scratchpad / Snippet Intake

Use this section to quickly drop new trip wires before they are organized.

- *Empty for now.*
