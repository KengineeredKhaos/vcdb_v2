## Policy Catalog v2.0 — 10 consolidated policies

### 1) `policy_finance_taxonomy.json`

**Purpose:** one place for *finance semantics* (names/tags), not account pairs.  
**Consumes:** Finance, Ops (hints), Sponsors (pledge types).  
**From v1:** `policy_fund_archetype.json`, `policy_journal_flags.json`  
**Add here (new):** `expense_kinds` (small, controlled list) so Ops can reference finance semantics without “word salad”.

**Sections**

- `fund_archetypes[]` (restriction_type, payment_timing, label)

- `journal_flags[]` (key, label, what it means)

- `expense_kinds[]` (key, label) ← semantic tags for mapping tasks → finance

---

### 2) `policy_finance_controls.json`

**Purpose:** authority + caps + budget periods (the “hard rules”).  
**Consumes:** Finance, Admin/Governance enforcement.  
**From v1:** `policy_spending.json`, `policy_budget.json`

**Sections**

- `spending.staff_cap_cents`

- `spending.class_caps{...}`

- `spending.approvers{...}`

- `budget.periods[]`

> This merge eliminates the duplicate cap problem you currently have (`policy_issuance.spending_staff_cap_cents` and `policy_spending.staff_cap_cents`). In v2, spending caps live **only here**.

---

### 3) `policy_operations.json`

**Purpose:** unify **Calendar/Project/Task** and define the *bridge vocabulary* to Finance without embedding Finance internals.  
**Consumes:** Calendar, Finance (as hints), Admin UI.  
**From v1:** `policy_calendar.json`, `policy_projects.json`

**Sections**

- `task_kinds[]` (canonical keys + human labels + **finance_hints**)

- `projects{project_ulid: {...}}` (blackouts + optional project metadata)

**The Finance bridge (keep it clean):**

- `task_kinds[].finance_hints.expense_kinds[]` → references keys from `policy_finance_taxonomy.expense_kinds`

- optional `task_kinds[].finance_hints.default_flags[]` → references `journal_flags`

- optional `task_kinds[].finance_hints.allowed_fund_archetypes[]` → references `fund_archetypes`

That gives you a stable “semantic mapping” without pushing chart-of-accounts details into Governance.

---

### 4) `policy_entity_roles.json`

**Purpose:** domain roles + assignment rules + POC scopes (your rename is perfect).  
**Consumes:** Auth/Governance integration, Entity slice, Admin.  
**From v1:** `policy_domain.json`, `policy_poc.json`

**Sections**

- `domain_roles[]`

- `assignment_rules{...}`

- `poc_scopes[]`, `default_scope`, `max_rank`

---

### 5) `policy_customer.json`

**Purpose:** customer eligibility + needs tiers + verification taxonomy.  
**Consumes:** Customers, Eligibility decisioning, Logistics eligibility gates.  
**From v1:** `policy_customer_needs.json`, `policy_eligibility.json`

**Sections**

- `veteran_verification_methods[]`

- `tiers[]`

- `eligibility.map{...}`

- `eligibility.defaults{...}`

---

### 6) `policy_locations.json`

**Purpose:** location vocabulary + matching patterns.  
**Consumes:** Calendar, Logistics, Finance (tags), reporting.  
**From v1:** `policy_locations.json` (unchanged conceptually)

**Sections**

- `kinds[]`

- `locations[]`

- `patterns[]`

(Keep separate: it’s an operational “lookup” and often changes independently.)

---

### 7) `policy_service_taxonomy.json`

**Purpose:** unify all “service/capability vocabularies” so keys don’t drift.  
**Consumes:** Resources, Sponsors, matching logic.  
**From v1:** `policy_classification.json`, `policy_resource_capabilities.json`, `policy_sponsor_capabilities.json`

**Sections**

- `classifications[]` + `sku_code_regex`

- `resource_capabilities{ classifications[...] … }`

- `sponsor_capabilities{ domains[...] … }`

This is the cleanest place to avoid key explosion: “one policy = the vocabulary.”

---

### 8) `policy_logistics_issuance.json`

**Purpose:** SKU constraints + issuance decisioning + cadence rules (one pipeline).  
**Consumes:** Logistics issuance services + enforcers.  
**From v1:** `policy_sku_constraints.json`, `policy_issuance.json`

**Sections**

- `sku_constraints.rules[]`

- `sku_constraints.allowed_units[]`

- `sku_constraints.allowed_sources[]`

- `issuance.defaults{...}`

- `issuance.rules[]`

- `coverage_mode`, `default_behavior`

**Important v2 rule:** remove any finance caps from here. Issuance references spending authority only via semantics (or by calling Finance/Governance contracts), not by re-declaring caps.

---

### 9) `policy_lifecycle.json`

**Purpose:** all state machines and allowed transitions in one place.  
**Consumes:** Logistics item lifecycle, Resources readiness/MOU, Sponsors readiness/MOU/pledge.  
**From v1:** `policy_state_machine.json`, `policy_resource_lifecycle.json`, `policy_sponsor_lifecycle.json`, `policy_sponsor_pledge.json`

**Sections**

- `machines{...}` containing:
  
  - `logistics.item_lifecycle`
  
  - `resource.readiness`, `resource.mou`
  
  - `sponsor.readiness`, `sponsor.mou`
  
  - `sponsor.pledge_status` (types/statuses/transitions)

---

### 10) `policy_governance_index.json` (small but powerful)

**Purpose:** the manifest / catalog that Admin + CLI will use to load/validate/edit policies safely.  
**Consumes:** Admin policy editor + CLI policy tools + policy health checks.  
**New in v2.**

**Sections**

- `policies[]`: `{ policy_key, filename, schema_filename, owner_role, edit_cadence_hint }`

This is what prevents “we renamed a policy file and half the app still expects the old name.”

---

## Migration plan: 20 → 10 without drift

### Step 1 — Write the catalog and freeze it

- Create `policy_governance_index.json`

- Define the 10 policy keys + filenames + schemas.

### Step 2 — Build v2 policies and schemas side-by-side

- Create the 10 v2 files in governance/data (or a `data/v2/` subfolder if you prefer clean separation during migration).

- Align schemas to these v2 shapes (strict `additionalProperties: false` everywhere).

- Add the `meta` header to every file.

### Step 3 — Update loader plumbing once

- `extensions/policies.py` reads the manifest and exposes typed loaders by `policy_key`.

- `policy_health_report()` validates **every** entry in the manifest (schema + semantic).

### Step 4 — Move consumers slice-by-slice

- Logistics: switch to `policy_logistics_issuance`

- Calendar/Ops: switch to `policy_operations`

- Finance: switch taxonomy + controls

- Resources/Sponsors: switch service taxonomy + lifecycle

### Step 5 — Delete v1 policies

Once tests + CLI flows are green, remove the old 20 files and their schemas.

---

## Keeping the Finance bridge clean (no word salad)

The trick is to **cap the number of cross-slice tags** and make them *referential*:

- Ops produces: `task_kind`

- Finance taxonomy defines: `expense_kind`, `journal_flag`, `fund_archetype`

- Ops references those by **key only** under `finance_hints`

- Finance decides account pairs internally.

That prevents governance JSON from turning into an accounting system.

---

If you want, next message I can lay out the **exact mapping table** (“old file → new file.section”) for all 20 policies so you have a migration checklist you can literally tick through.
