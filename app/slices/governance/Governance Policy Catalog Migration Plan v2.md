Below is a **v1 → v2.0 mapping table** you can keep open while you migrate over multiple sessions. It’s written as a **checklist**: each row tells you exactly *where the content goes*, what gets **renamed**, what gets **deleted**, and what to watch for.

I’m assuming your new v2.0 rule is already in force:

- **Every policy file has `meta`** (title/description/notes/policy_key/version/status/schema_version/effective_on)

- **No legacy top-level `version/notes`** (you’re deleting them everywhere)

- **Strict schemas** (`additionalProperties: false` everywhere)

---

## Governance Policy Catalog v2.0 (10 files)

1. `policy_governance_index.json` *(new)*

2. `policy_finance_taxonomy.json`

3. `policy_finance_controls.json`

4. `policy_operations.json`

5. `policy_entity_roles.json`

6. `policy_customer.json`

7. `policy_locations.json`

8. `policy_service_taxonomy.json`

9. `policy_logistics_issuance.json`

10. `policy_lifecycle.json`

---

## Mapping table: v1 (20 files) → v2.0 (10 files)

| v1 policy file                      | v2.0 destination                               | Move these keys / sections                                                                                                                              | Notes & guardrails                                                                                                                                                                                                                                                                                                     |
| ----------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `policy_budget.json`                | `policy_finance_controls.json`                 | `periods[]` → `budget.periods[]`                                                                                                                        | Keep the line structure intact at first. **Schema fix needed**: your v1 uses status `unfunded`; ensure v2 schema allows it (or rename to `draft`). Consider later whether `project_type_key`/`project_code` should be normalized to `operations.project_types` or `operations.projects`.                               |
| `policy_spending.json`              | `policy_finance_controls.json`                 | `staff_cap_cents` → `spending.staff_cap_cents`; `class_caps` → `spending.class_caps`; `approvers` → `spending.approvers`                                | **Single source of truth** for spending caps. This is where the “duplicate cap drift” gets killed.                                                                                                                                                                                                                     |
| `policy_fund_archetype.json`        | `policy_finance_taxonomy.json`                 | `fund_archetypes[]` → `fund_archetypes[]`                                                                                                               | In v2: require `restriction_type` + `payment_timing` per archetype. Notes move to `meta.notes`.                                                                                                                                                                                                                        |
| `policy_journal_flags.json`         | `policy_finance_taxonomy.json`                 | `flags[]` → `journal_flags[]`                                                                                                                           | Consider renaming item key from `key` to `code` only if you’re doing it *everywhere*; otherwise keep `key`. Notes move to `meta.notes`.                                                                                                                                                                                |
| `policy_projects.json`              | `policy_operations.json`                       | `task_kinds[]` → `task_kinds[]`; `defaults` → `defaults`                                                                                                | **Finance bridge:** rename `allowed_expense_kinds` → `finance_hints.expense_kinds` and make those values reference `policy_finance_taxonomy.expense_kinds[].key`. Your current `defaults.expense_kind` becomes `defaults.finance_hints.expense_kind` (or `defaults.expense_kind_key`).                                 |
| `policy_calendar.json`              | `policy_operations.json`                       | `projects.{ulid}.blackout_rules[]` → `projects.{ulid}.blackout_rules[]`                                                                                 | Keep blackout rule shapes identical. This stays *pure scheduling semantics*.                                                                                                                                                                                                                                           |
| `policy_domain.json`                | `policy_entity_roles.json`                     | `domain_roles[]` → `domain_roles[]`; `assignment_rules` → `assignment_rules`                                                                            | This becomes the canonical “domain role vocabulary + assignment policy.” Strong guardrail: **no schema leakage** (no table names, no ORM paths).                                                                                                                                                                       |
| `policy_poc.json`                   | `policy_entity_roles.json`                     | `poc_scopes[]` → `poc.poc_scopes[]`; `default_scope` → `poc.default_scope`; `max_rank` → `poc.max_rank`                                                 | Your v1 had no version key; v2 meta fixes that.                                                                                                                                                                                                                                                                        |
| `policy_customer_needs.json`        | `policy_customer.json`                         | `veteran_verification_methods[]` → `verification.veteran_methods[]`; `tiers` → `needs.tiers`                                                            | Keep tier names stable (`tier1/tier2/tier3`) unless you want a wider redesign.                                                                                                                                                                                                                                         |
| `policy_eligibility.json`           | `policy_customer.json`                         | `defaults` → `eligibility.defaults`; `map` → `eligibility.map`                                                                                          | **Important guardrail:** your v1 map values look like dotted paths (`customer.is_veteran_verified`). That’s *schema leakage by your own definition*. In v2, replace these with **semantic factor keys** (e.g., `customer.veteran_verified`) and let the *Customer slice* map factor keys to its own fields internally. |
| `policy_locations.json`             | `policy_locations.json` *(stays its own file)* | `kinds[]`, `locations[]`, `patterns{}`                                                                                                                  | Keep separate. This file is a “lookup vocabulary” and will change independently.                                                                                                                                                                                                                                       |
| `policy_classification.json`        | `policy_service_taxonomy.json`                 | `sku_code_regex` → `classifications.sku_code_regex`; `classifications{}` → `classifications.map{}`                                                      | Your v1 `classifications` is a dict keyed by classification codes; keep that shape (it’s efficient and stable).                                                                                                                                                                                                        |
| `policy_resource_capabilities.json` | `policy_service_taxonomy.json`                 | `classifications{domain: [keys...]}` → `resource_capabilities.by_domain{...}`; `note_max` → `resource_capabilities.note_max`                            | This is “resource can do X” vocabulary, not a workflow state machine.                                                                                                                                                                                                                                                  |
| `policy_sponsor_capabilities.json`  | `policy_service_taxonomy.json`                 | `domains[]` → `sponsor_capabilities.domains[]`                                                                                                          | Your v1 file currently has invalid JSON (missing comma). In v2, rewrite cleanly. Treat it as taxonomy: domains + keys with labels/descriptions.                                                                                                                                                                        |
| `policy_sku_constraints.json`       | `policy_logistics_issuance.json`               | `allowed_units[]` → `sku_constraints.allowed_units[]`; `allowed_sources[]` → `sku_constraints.allowed_sources[]`; `rules[]` → `sku_constraints.rules[]` | These rules derive “issuance_class” from SKU parts. Keep rule semantics; rename `if/then/why` only if you standardize across all rule sets.                                                                                                                                                                            |
| `policy_issuance.json`              | `policy_logistics_issuance.json`               | `defaults` → `issuance.defaults`; `rules[]` → `issuance.rules[]`; `coverage_mode`, `default_behavior` → `issuance.coverage_mode/default_behavior`       | **Delete** `spending_staff_cap_cents` from issuance (it belongs only in `policy_finance_controls.spending.staff_cap_cents`). If issuance needs spending authority, it should consult Finance/Governance via contracts, not re-declare the number.                                                                      |
| `policy_state_machine.json`         | `policy_lifecycle.json`                        | `machines{}` → `machines{}`                                                                                                                             | This is the foundation of lifecycle consolidation. Keep your `logistics.item_lifecycle` machine as-is and add the others into the same `machines` dict.                                                                                                                                                                |
| `policy_resource_lifecycle.json`    | `policy_lifecycle.json`                        | `readiness_status_allowed[]` + `mou_status_allowed[]` → `machines.resource.readiness / machines.resource.mou`                                           | Convert “allowed lists” into a machine with `states[]` and (optional) `transitions{}`. If you truly don’t want transitions for resources yet, set transitions to “any → any” or omit transitions and let schema allow it.                                                                                              |
| `policy_sponsor_lifecycle.json`     | `policy_lifecycle.json`                        | `readiness`/`mou`/`transitions` → `machines.sponsor.readiness` + `machines.sponsor.mou`                                                                 | This one already resembles a machine but with richer state objects (`label`, `can_issue`). In v2 lifecycle schema, support **state attributes** (e.g., `states[{code,label,can_issue}]`).                                                                                                                              |
| `policy_sponsor_pledge.json`        | `policy_lifecycle.json`                        | `types[]`, `statuses[]`, `transitions{}` → `machines.sponsor.pledge_status` + `pledge.types`                                                            | Decide if pledge “types” are taxonomy (finance-ish) or lifecycle. My recommendation: keep `types[]` as taxonomy under `policy_finance_taxonomy` *or* under `policy_service_taxonomy` (sponsor taxonomy). Put pledge **statuses/transitions** in lifecycle.                                                             |

---

## Cross-cutting guardrails for the migration

These are the “don’t let future-you regret this” rules:

### Guardrail A — Zero duplication of numeric limits

If it’s a **cap/authority**, it lives in **one place**: `policy_finance_controls`.

- No spending caps inside issuance, calendar, projects, etc.

### Guardrail B — No schema leakage in eligibility / mapping policies

Anywhere you currently have dotted strings like `customer.is_veteran_verified`:

- Replace with semantic factor keys (e.g., `customer.veteran_verified`)

- The *Customer slice* owns the translation from factor keys → its own fields

### Guardrail C — Taxonomy keys must be small and stable

To avoid “word salad,” keep cross-slice tags to short controlled lists:

- `expense_kind`

- `journal_flag`

- `fund_archetype`

- `task_kind`

- `classification_code`

Additive only. Renames require a migration plan.

### Guardrail D — `policy_governance_index` becomes the *only* catalog

Admin tools and CLI tools should read the manifest and validate:

- policy exists

- schema exists

- `meta.policy_key` matches the manifest entry

- schema validates

- semantic checks pass

This makes renames safe later.

---

## Suggested migration order (minimizes breakage)

1. Create `policy_governance_index.json` first (even if it points to v1 for a moment).

2. Build these v2 files first (highest value / lowest coupling):
   
   - `policy_finance_controls`
   
   - `policy_logistics_issuance`
   
   - `policy_lifecycle`

3. Then unify ops mapping (the finance bridge):
   
   - `policy_finance_taxonomy`
   
   - `policy_operations`

4. Then unify identity/roles and customer:
   
   - `policy_entity_roles`
   
   - `policy_customer`

5. Then consolidate service vocab:
   
   - `policy_service_taxonomy`

6. Keep `policy_locations` intact; just add `meta` and tighten schema.

---

If you want, next I can turn this mapping into a **checkbox migration worksheet** (same content, but formatted as “Step / File / Change / Done”) so you can log progress across days without rereading the whole table.
