# Foundation Hardening Pass

## 1. Auth (“Foyer / Drop Zone”)

**Goal:** Safe place where users “take their shoes off” before touching anything important. Login, roles, basic hygiene.

**Tasks**

1. **Auth slice hardening**
   
   - **What:**
     
     - Confirm login/logout flows are final (no more TODO auth flows hiding in routes).
     
     - Make sure password hashing is centralized (your `hashing.py` helpers) and *only* used via Auth.
     
     - Lock down role assignment paths (no casual role escalation).
   
   - **State:**
     
     - Rough Auth is there; tests proved basic login works; logging/chrono/ids canonized.
     
     - Role semantics are known (user/staff/admin/auditor/dev) and mapped to Governance domain roles — but we haven’t done a “final pass” on the Auth slice as a whole.
   
   - **Priority:** **High.** This is the front door.

2. **Session / security hygiene**
   
   - **What:**
     
     - Enforce secure cookie flags (in config, not code sprinkling).
     
     - Decide on session lifetime / idle timeout.
     
     - Add “too many failed logins” logic or at least a TODO + Governance policy stub.
   
   - **State:**
     
     - Hooks and config patterns are in place, but we haven’t walked through and said, “Yep, this is the final story.”
   
   - **Priority:** **High**, but can be split into: “baseline now, fancy later.”

3. **Auth → Admin “doorway”**
   
   - **What:**
     
     - A single, boring route like `/admin/` that is:
       
       - RBAC-guarded (`admin` only),
       
       - clearly the “entrance” to all future Admin tooling.
   
   - **State:**
     
     - Rough Admin slice exists, but the “front door” UX is not finalized.
   
   - **Priority:** **Medium–High**, because it ties Auth and Admin together.

---

## 2. Admin slice (Office / Control Room)

**Goal:** Future place where non-dev admins manage policy, archives, health checks, etc.

**Tasks**

1. **JSON policy editor scaffolding (read-only first)**
   
   - **What:**
     
     - A simple Admin view that lists the Governance policy files (the JSON we just wired and validated).
     
     - Can open one and show:
       
       - raw JSON, and
       
       - a summarized “what this policy controls” view.
   
   - **State:**
     
     - Governance policies + schemas + validate pipeline exist; CLI `policy-health` works.
     
     - Admin UI for policies is **not** in place yet (only dev CLI).
   
   - **Priority:** **Medium.** Not needed to issue gear, but critical before “other humans” administer the system.

2. **Ledger/Journal health & future archive hooks**
   
   - **What:**
     
     - Admin-only pages/CLI to:
       
       - run `ledger-verify` and show status,
       
       - show rough ledger row counts and growth over time,
       
       - stub out “archive older than X” (no need to implement actual move-yet, just design the interface).
   
   - **State:**
     
     - Ledger verify CLI exists; events now correlate via `request_id`.
     
     - No Admin-facing “I can see my ledger health” yet.
   
   - **Priority:** **Medium.** Architecturally important, not blocking day-to-day ops yet.

---

## 3. Governance & Policy

You’ve actually done a lot here:

- Policy JSON files and schemas for domain/issuance/sku/location/etc.

- Validators wired via `validate.py`.

- `flask dev policy-health` plus the new SKU/locations summaries.

**Deferred tasks**

1. **Complete policy schema coverage & semantics checks**
   
   - **What:**
     
     - Finish the planned JSON Schemas + semantic checks for *all* policy_* files (some are more skeletal).
     
     - Make sure `policy-health` checks the “big three” for flows we care about:
       
       - eligibility,
       
       - issuance,
       
       - spending/funding.
   
   - **State:**
     
     - Key pieces (issuance, sku_constraints, locations, domain roles) are validated.
     
     - Some policy files are likely “syntax OK but semantics TBD.”
   
   - **Priority:** **Medium–High**, because everything else leans hard on these being trustworthy.

2. **Governance → Admin contracts**
   
   - **What:**
     
     - Read-only contracts that expose policy summaries to Admin slice (no UI logic in Governance).
   
   - **State:**
     
     - Concept talked about (extensions/contracts governance_v2), basic shape exists, not fully fleshed for all policies.
   
   - **Priority:** **Medium.** Will matter when we start Admin UI.

---

## 4. Ledger (roof) & Finance Journal (matching roof panel)

Ledger:

- Hash-chained, verified, events keyed by ULID, no PII.

- We just added nice correlation via `request_id` and `domain`/`operation`.

Finance Journal:

- Intended to be the “money ledger” parallel to system Ledger.

**Deferred tasks**

1. **Finance journal model & API hardening**
   
   - **What:**
     
     - Finalize `finance_journal` models and enums (income/expense, allocation, reimbursement, etc.).
     
     - Ensure all journal entries are:
       
       - append-only,
       
       - tied to ULIDs (sponsor, project, allocation, etc.),
       
       - emitted in lockstep with ledger events (Finance→Ledger).
   
   - **State:**
     
     - Journal models and migrations sketched, but we explicitly tabled `finance_v2` contract work.
   
   - **Priority:** **High**, because you want Sponsor funds on the same footing as Logistics.

2. **Sponsor funding model ↔ Finance journal**
   
   - **What:**
     
     - Wire Sponsors slice to:
       
       - record pledges / donations into Finance Journal,
       
       - track allocations from those pledges,
       
       - enforce caps / restrictions (Board governance rules).
   
   - **State:**
     
     - Sponsor contracts/services sketched; policies exist (sponsor capabilities, pledge, lifecycle).
     
     - Full Sponsor↔Finance linkage is not done.
   
   - **Priority:** **High.** This is a big structural beam.

3. **Journal ↔ Ledger contract**
   
   - **What:**
     
     - Ensure every finance_journal write:
       
       - emits a matching Ledger event (finance.* domain),
       
       - uses `request_id` from caller for correlation.
   
   - **State:**
     
     - Concept is established, but the actual Finance→Ledger emit path is incomplete.
   
   - **Priority:** **Medium–High.**

---

## 5. Logistics (you just leveled this room)

**Current state (post-work):**

- SKU construction & constraints: policy + schema + services wired.

- Locations & rackbins: policy + schema + services wired.

- `ensure_item`, `receive_inventory`: No-Garbage-In, policy-backed.

- `decide_and_issue_one`:
  
  - enforcer → governance → stock resolution → low-level issue,
  
  - ledger emit on all outcomes,
  
  - `request_id` correlation.

- CLI seeding & `policy-health` show the whole picture.

**Deferred tasks (Logistics-specific)**

1. **Customer History view (from Customer workflow)**
   
   - **What:**
     
     - A Customer slice service that answers:
       
       - “What has this customer been issued?”
       
       - (Probably by querying Logistics tables, not by projecting from Ledger.)
   
   - **State:**
     
     - Not implemented yet; only Logistics tables + ledger events exist.
   
   - **Priority:** **Medium.** You can issue gear without this, but it’s key for UI.

2. **Extra ledger emits (receive/movement)**
   
   - **What:**
     
     - `logistics.receive.created` when stock is received.
     
     - Possibly `logistics.movement.created` distinct from `issue.created`.
   
   - **State:**
     
     - Only the high-level issuance event exists.
   
   - **Priority:** **Medium–Low**; nice-to-have for audit, but not blocking ops.

---

## 6. Entity, Customer Core & Customer Profile

**Entity slice:**

- ULID-based identity, PII boundaries, Person/Org separation — mostly canonized.

**Customer slice:**

- Baseline create/update flows, basic DTOs, and a “dashboard”/view concept.

**Deferred tasks**

1. **Customer Profile canonization**
   
   - **What:**
     
     - Decide precisely what lives in Customer Profile vs. Governance policy vs. Attachments.
     
     - Lock down the fields, enums, and Governance mapping (e.g., needs tiers).
   
   - **State:**
     
     - Concept is there; implementation partially done.
   
   - **Priority:** **High**, because Customer ↔ Resource matching depends on a reliable profile.

2. **Customer↔Resource pairing workflow**
   
   - **What:**
     
     - A service flow (probably a dedicated “match_resources_for_customer.py” service module) that:
       
       - takes Customer Profile + Governance policies,
       
       - filters Resources by capabilities, eligibility, blackout, funding availability,
       
       - returns matches + required Sponsor/Finance actions.
   
   - **State:**
     
     - Heavily discussed conceptually; not implemented as a concrete flow yet.
   
   - **Priority:** **High.** This is one of the core “what the system actually does” flows.

3. **Customer History (as you just framed it)**
   
   - **What:**
     
     - A Customer-service-level “history view” that queries Logistics for what has been issued to this customer.
     
     - Optional ledger “pii_view” event for viewing history.
   
   - **State:**
     
     - Not started; we just agreed it should originate in Customer, not Logistics.
   
   - **Priority:** **Medium.**

---

## 7. Resources, Sponsors & Capabilities

**Resources:**

- Capabilities taxonomy & policy JSON exist (classification, capabilities, lifecycle).

**Sponsors:**

- Capabilities, pledge/constraint policies, governance rules defined.

**Deferred tasks**

1. **Resource capabilities & readiness workflow**
   
   - **What:**
     
     - A Resources service that:
       
       - interprets capability matrix + readiness status (draft→review→active→suspended),
       
       - exposes “is this resource eligible for Customer X at time Y?” to matching flows.
   
   - **State:**
     
     - Policy + taxonomy defined; services partially sketched.
   
   - **Priority:** **High**, because this is half of Customer↔Resource matching.

2. **Contact Sheet contracts (Resource/Sponsor POCs)**
   
   - **What:**
     
     - `OrgContactDTO`, `PersonContactDTO`, `ContactSheetDTO` and a contract like:
       
       - `get_contact_sheet_for_resource(resource_ulid)`
       
       - `get_contact_sheet_for_sponsor(sponsor_ulid)`
     
     - Optionally emit `pii_view` ledger events when these are used.
   
   - **State:**
     
     - Designed conceptually; contract not yet implemented.
   
   - **Priority:** **Medium–High**, since this is what gets handed to staff/Customer as “who do I call?”

---

## 8. Calendar / Projects / Task Management

**Goal:** Where funding windows, blackout windows, and operational tasks live.

**Deferred tasks**

1. **Calendar/Task baseline**
   
   - **What:**
     
     - Basic models for:
       
       - events (deadlines, appointments, follow-up tasks),
       
       - projects (e.g. “Welcome Home kit for Customer X” with a budget),
       
       - linkages to Sponsors/Finance allocations.
   
   - **State:**
     
     - Skeleton Calendar slice exists, some enforcer hooks (blackout policy) already working.
     
     - Project/funding linkage is not yet built out.
   
   - **Priority:** **Medium–High**, given your desire for Project+fund tracking.

2. **Integration with Finance & Governance**
   
   - **What:**
     
     - When Finance commits an allocation > $X, a Calendar task is created for Treasurer (per Governance policy).
     
     - When certain events happen (delivery, receipts transfer), Calendar tasks track them.
   
   - **State:**
     
     - Policies discuss it; implementation is still to come.
   
   - **Priority:** **Medium.**

---

## 9. Attachments (Document Storage + Retention)

**Goal:** Store DD-214s, MOUs, receipts, etc., with retention rules.

**Deferred tasks**

1. **Attachment slice model + storage**
   
   - **What:**
     
     - Tables & storage mechanism (likely file paths under a var/attachments folder with metadata in DB).
     
     - Clear enforcement of PII and access rules.
   
   - **State:**
     
     - Not really started; mostly at the “we know we’ll need this” stage.
   
   - **Priority:** **Medium**, but will climb once Finance/Receipts and MOU docs go live.

2. **Retention policy**
   
   - **What:**
     
     - Governance JSON for retention (e.g., “receipts 7 years, DD-214 forever, MOUs X years after expiry”).
     
     - Admin job/CLI to enforce by:
       
       - flagging,
       
       - archiving,
       
       - or deleting (within policy).
   
   - **State:**
     
     - Discussed conceptually; not implemented.
   
   - **Priority:** **Medium.**

---

## 10. UI / Forms (WTF, SelectFields, Templates)

**Goal:** Make the system usable without a CLI or direct DB pokes.

**Deferred tasks**

1. **Forms & SelectField plumbing**
   
   - **What:**
     
     - Define forms that are driven by Governance policy (choices populated from JSON, not hard-coded lists).
     
     - Make sure SelectFields don’t drift from policy enums.
   
   - **State:**
     
     - Basics exist in a few slices; not standardized across the app.
   
   - **Priority:** **Medium–High**, once you start real template work.

2. **Basic admin/staff UI for core flows**
   
   - **What:**
     
     - Login, see dashboard, find Customer, see matching Resources, issue items, log allocations, etc.
   
   - **State:**
     
     - Routes/templates are mostly skeletons; we’ve intentionally deferred heavy UI until foundation was strong.
   
   - **Priority:** **High** once you declare “foundation is good enough.”

---

## Where the heaviest priorities sit (given your momentum)

Based on what you just said and where the code is strongest right now, I’d rank the next “big rocks” like this:

1. **Auth & Admin foyer/office DONE**
   
   - Firm up Auth slice (foyer).
   
   - Wire a simple Admin front door and a read-only policy viewer.
   
   - Reason: that’s your human-facing entrance and sets the tone for everything else.

2. **Finance Journal + Sponsor funding link**
   
   - Bring Finance up to “No-Garbage-In” and “emit-to-ledger” parity with Logistics.
   
   - Wire Sponsor pledges/allocations into the journal.
   
   - Reason: you want money flows as solid as gear flows before UI.

3. **Customer Profile & Resource Capabilities matching**
   
   - Canonize Customer Profile data shape.
   
   - Implement a clean “match_resources_for_customer” service that uses Governance policies.
   
   - Reason: this is the core “VCDB actually does something useful” workflow.

4. **Calendar/Tasks hook into Finance & Logistics**
   
   - Enough to track key dates (e.g., receipts, reimbursement follow-ups, blackout enforcement).
   
   - Reason: makes policy real over time instead of just static rules.

5. **Attachments & retention**
   
   - Start with receipts/MOUs and a basic retention JSON policy, even if the Admin job is manual at first.

Logistics, Ledger, and your policy infrastructure are solid enough now that we *can* safely layer on UI/templates and future Admin tooling without discovering “oh, this whole thing is built on sand.”

If you want, next step we can pick *one* of those top three (Auth, Finance+Sponsors, or Customer+Resources matching) and break it into a mini design brief the way we did for Logistics — then march through it the same way.

---

# Major Revisions

Gotcha. Let’s freeze what we’ve agreed to before we touch any code.

I’ll break it into:

- **A. Conceptual decisions (pinned)**

- **B. Slice-by-slice revisions / TODOs**

So you can treat this as a punch list.

---

## A. Conceptual decisions (pinned)

- **1. Allocation is project-centric, not customer-centric**
  
  - `Allocation` should link **sponsor money → project**, not directly to a customer.
  
  - A sponsor fund dedicated to a single customer becomes a **micro-project** (e.g. “Emergency Rent for CUST-X / Jan 2026”).
  
  - Anywhere we previously used `customer_ulid` on allocations, we move to `project_ulid`.

- **2. Distinct roles for slices**
  
  - **Sponsors**: relationships + pledges + **FundingProspect** (who might give, how much, for what).
  
  - **Calendar**: projects and tasks (when/what work happens; which project an expense belongs to).
  
  - **Finance**: *facts* (journal entries, funds, projects, linking receipts/spends to projects and funds).
  
  - **Governance**: rules + policy (flags, fund archetypes, project types, spending caps, eligibility, etc.).

- **3. Project type taxonomy (policy, not DB magic)**
  
  - We’ll define a `project_types` catalog in **Governance policy JSON** (e.g. `policy_projects.json`) with keys like:
    
    - `operations`, `overhead`, `travel`, `freight`, `solicitation`, `recruitment`,  
      `fund_raising`, `sponsor_recognition`, `lateral`, `outreach`,  
      `stand_down`, `memorial_ride`, `veterans_ride`.
  
  - Actual Calendar/Finance projects will **reference a `project_type_key`** from this catalog.

- **4. Fund archetypes (Governance policy, used by Finance/Sponsors)**
  
  - We’ll maintain a `fund_archetypes` list in Governance (e.g. `policy_funding.json`), including:
    
    - `general_unrestricted`
    
    - `grant_advance`
    
    - `grant_reimbursement`
    
    - `vet_only`
    
    - `local_only`
    
    - `local_vet_only`
    
    - `match_funds`
    
    - `inkind_tracking`
  
  - Each **Fund** in Finance will carry an `archetype_key` that must match this policy.

- **5. Journal flags are governance-controlled, not ad-hoc**
  
  - No more “search memo for ‘inkind’.”
  
  - Governance policy will define allowed **journal flags** (e.g. `policy_journal_flags.json`), including:
    
    - `inkind`
    
    - `reimbursable`
    
    - `grant_elks_freedom`
  
  - Finance Journal will have a `flags` field; all values must be validated against that policy.

- **6. Budget = board-adopted spending caps (Governance), NOT forecasts**
  
  - Budget is **not** “we think we’ll raise X”; it’s:
    
    > “For this fund + project + period, we’ll cap spending at N unless an authorized override happens.”
  
  - Budget data will live as Governance policy JSON (e.g. `policy_budget.json`) with lines like:
    
    - `(period_label, fund_archetype_key/fund_code, project_type_key/project_code, amount_cents, status=draft|adopted, source=board|grant:... )`.
  
  - **Finance never owns Budget**; it just calls Governance to see what caps apply and compares them to actual spend.

- **7. Forecasts & “hopes” live in Sponsors as FundingProspect**
  
  - All “we *might* get between X and Y from Elks/Joe Snuffy/etc.” belongs in **Sponsors.FundingProspect**, not in Budget.
  
  - FundingProspect is a CRM/planning tool, not an enforcement tool.

- **8. FundingProspect must exist now in Sponsors**
  
  - We add a **FundingProspect model** in the Sponsors slice to track:
    
    - Which sponsor, what type of funding (via `fund_archetype_key`), optional `project_type_key`.
    
    - `estimated_min_cents` / `estimated_max_cents`.
    
    - `realized_cents_cached` (actual receipts tied back from Finance).
    
    - Lifecycle fields: `status`, `confidence`, contact dates, notes.
  
  - This slice becomes the home for **fundraising planning and “bang for the buck” metrics**.

- **9. Finance ↔ FundingProspect linkage via ULID and contracts**
  
  - Finance Journal entries for **receipts** can carry an optional `prospect_ulid` (raw ULID, no DB FK).
  
  - Finance exposes a contract like `get_prospect_realization(prospect_ulid)` that:
    
    - Aggregates all receipts tagged with that ULID.
    
    - Returns totals & basic stats (`total_receipts_cents`, first/last dates…).
  
  - Sponsors calls this contract and updates `FundingProspect.realized_cents_cached` + `realized_updated_at`.

- **10. Budget enforcement = Governance policy + Finance actuals**
  
  - Governance provides “what is the cap for this fund + project + period?” via a contract.
  
  - Finance (or an enforcer) provides “how much have we actually spent so far?”.
  
  - A **budget decision** function compares requested spend vs cap and returns:
    
    - `allowed`, `reason`, `approver_required`, `remaining_cents`, etc.

---

## B. Slice-by-slice revisions / TODOs

### 1. Governance slice

**New / updated policies**

- `policy_projects.json`
  
  - Add `project_types` array with the keys/labels we discussed.

- `policy_funding.json`
  
  - Add/confirm `fund_archetypes` list and definitions (including `match_funds`).

- `policy_journal_flags.json`
  
  - Define allowed `flags` for Finance Journal.

- `policy_budget.json`
  
  - Define **budget caps** per:
    
    - `period_label`
    
    - `fund_archetype_key` and/or `fund_code`
    
    - `project_type_key` and/or `project_code`
    
    - `amount_cents`
    
    - `source` (`board`, `grant:ELKS_FREEDOM`, etc.)
    
    - `status` (`draft`/`adopted`)

**Semantics / helpers**

- In `policy_semantics.py` (or similar):
  
  - `assert_journal_flags_ok(flags: list[str])`
    
    - Load `policy_journal_flags.json`, raise if any flag is unknown.
  
  - Budget helpers, e.g.:
    
    - `get_budget_caps(...)` or `find_budget_cap(...)`
      
      - Lookup applicable cap for (fund archetype/fund code, project type/project code, period, status=adopted).
  
  - Possibly simple validators for project types and fund archetypes for Admin/Finance UIs.

**Admin integration**

- Admin slice (not Governance itself) will get:
  
  - Policy editor for Budget, using JSON schema, similar to other policy files.
  
  - Buttons/flows to toggle `status` between `draft` and `adopted`.

---

### 2. Sponsors slice

**Models**

- Update `Allocation`:
  
  - Replace `customer_ulid` with `project_ulid`.
  
  - Treat customer-specific allocations via micro-projects (Calendar/Projects will represent them; Sponsors only sees `project_ulid`).

- Add `FundingProspect` model with (roughly):
  
  - `ulid`
  
  - `sponsor_ulid`
  
  - `label`, `description`
  
  - `fund_archetype_key` (validated against Governance `fund_archetypes`)
  
  - `primary_project_type_key` (optional; from Governance `project_types`)
  
  - `estimated_min_cents`, `estimated_max_cents`
  
  - `realized_cents_cached`, `realized_updated_at`
  
  - `status` (`new`, `researching`, `cultivating`, `asked`, `committed`, `declined`, `lapsed`, …)
  
  - `confidence` (`low` / `medium` / `high` or numeric)
  
  - `first_contact_on`, `last_contact_on`, `next_contact_on`
  
  - `notes`

**Contracts**

- In `sponsors_v2`:
  
  - Add DTOs and functions needed to:
    
    - Create/update FundingProspect records.
    
    - Query prospects for reporting (e.g., list active prospects and their estimated vs realized amounts).

**Services / CLI (later, but on the list)**

- CLI or admin helpers to:
  
  - List prospects with estimated vs realized totals (calling Finance contract).
  
  - Kick off a refresh of `realized_cents_cached` for all active prospects.

---

### 3. Finance slice

**Journal model**

- Add fields to Journal/JournalLine (depending on your current structure):
  
  - `flags` (string/JSON) – a set/list of governance-validated flags, e.g. `["inkind", "grant_elks_freedom"]`.
  
  - `prospect_ulid` (nullable, 26-char string) – for **receipt** entries tied to a FundingProspect.

**Contracts**

- In `finance_v2`:
  
  1. `get_prospect_realization(prospect_ulid) -> ProspectRealizationDTO`
     
     - Aggregate Journal receipts where `prospect_ulid` matches.
     
     - Return totals (and maybe breakdown by fund/period).
  
  2. Budget/actuals helper(s), something like:
     
     - `get_actual_spend(fund_ulid, project_ulid, period_label) -> ActualSpendDTO`

- These will be used by:
  
  - Sponsors (for FundingProspect realized amounts),
  
  - Enforcement (for budget checks).

**Validation**

- When logging Journal entries:
  
  - Call Governance semantics to validate `flags` (`assert_journal_flags_ok`).
  
  - Ensure `prospect_ulid` is just a raw ULID (no cross-slice FK).

---

### 4. Calendar slice

*(Mostly conceptual for now, but worth pinning)*

- Each **Project** should carry:
  
  - `project_type_key` from Governance `project_types`.
  
  - Optional short code (`project_code`) that can be used in Budget policy.

- Tasks may *optionally* carry:
  
  - `prospect_ulid` (for fundraising tasks tied to a particular FundingProspect).

- The eventual funding/request flow (later work):
  
  - Tasks that need money will reference a project; Finance/Governance will decide which fund to pull from and enforce budget caps.

No immediate schema changes required here to move forward on Governance/Sponsors/Finance, but we now know what fields Calendar should have when we firm up the project/task models.

---

### 5. Admin slice

*(Because it glues Governance policies to a UI)*

- Add/extend Admin UIs and services to edit new Governance policies:
  
  - `policy_projects.json`
  
  - `policy_funding.json` (if not already exposed)
  
  - `policy_journal_flags.json`
  
  - `policy_budget.json` (with schema validation + audit logging)

- Admin remains the only place Trustees/Officers change **policy JSON**, including budgets.

---

If you want, next we can pick **one slice at a time** and turn this list into concrete edits. My suggestion for order:

1. Governance policies & semantics (projects, fund archetypes, journal flags, budget skeleton).

2. Sponsors: `FundingProspect` model + basic DTO shape.

3. Finance: flags + `prospect_ulid` + `get_prospect_realization` contract.

That sequence will keep the data contracts straight before we start wiring any enforcement or UI.
