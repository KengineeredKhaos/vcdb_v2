# Project Ethos

- **Skinny routes, fat services.** Flask routes do almost nothing: parse input, call a service/contract, return a response.

- **Slices own their data.** Each slice owns its own tables and SQL. No cross-slice DB joins, no reaching into another slice’s models.

- **Only contracts expose slice data.** Cross-slice communication happens only via `app/extensions/contracts/*_vN.py`, never by importing slice internals.
  
  - Slice routes call *their own* services directly.
  
  - All **other** slices must only call another slice via its contracts (no direct imports of its models/services).

- **Ledger is the canonical record of “who did what when with whom and (sometimes) why.”**

- **Finance Journal is the canonical record of where money came from and where it went.**

- **Governance Policy is the canonical Board decision on how business is conducted.** Policy is JSON + JSON Schema; only the Admin slice can change/update policy at Board request.

---

## Core Architectural Decisions

### Slices & Responsibilities (v2 baseline)

- **Auth** – RBAC roles (`user`, `staff`, `admin`, `auditor`, etc.), login, session.
  
  - **"User Permissions": How the sausage is made.**

- **Entity** – People & org identity (ULID, PII, contact info). Only place full PII lives.
  
  - **"Who is whom": Absolutely Guarded above all other data !!!** 

- **Customers** – “Client” view on Entities (needs, eligibility, profile).
  
  - **"Who we serve":  what they need & what we can provide them.** 

- **Resources** – Service providers & capabilities (what can be offered).
  
  - **"The Suppliers": who has what to offer.**

- **Sponsors** – Donors, FundingProspects, CRM. **Inbound-only.**
  
  - **“The rainmaker”: inbound-only, CRM and pledge tracking.**

- **Logistics** – Physical items, SKUs, issuance, returns.
  
  - **"The Warehouse" the goods, where they are, where it went and who has 'em now.**

- **Finance** – Funds, Journal, balances, money facts (no PII).
  
  - **“The bookkeeper”: sees every cent, decides nothing, records facts.**

- **Governance** – Policy JSON & semantics: roles, restrictions, budgets, rules.
  
  - **“The board’s brain”: policies, caps, and decisions; never writes money rows directly.**

- **Calendar** – Projects & Tasks, scheduling, operational workflows.
  
  - **“The operations planner”: projects and tasks; the only thing that spends.**

- **Ledger** – Append-only event log for **all** slices (no PII).
  
  - **"Where Truth Lives": The immutable, auditable Source of Truth.**

- **Admin** – Maintenance & policy editing UI; the only slice allowed to mutate Governance policy files.
  
  - **"This is where shit goes horribly wrong": RTFM or GTFO!!!**

Future slices (e.g. Attachments, Web/public) plug into the same pattern.

### ULID Everywhere

- Every primary key is a 26-char ULID string.

- All foreign keys between slices are ULIDs.

- Ledger events store only ULIDs (no PII).

- Contracts/DTOs surface ULIDs, never raw DB IDs.

### PII Boundary

- **Only** Entity (and any “Party/Person Core” model) stores PII such as:
  
  - Names, addresses, phone, email.
  
  - Last-4 of SSN or similar.

- All other slices store **references only** (ULIDs, codes, labels).

- Ledger and logs never contain PII, only ULIDs and non-identifying labels.

---

## Contracts, DTOs, and Error Handling

### Contracts

- Live in `app/extensions/contracts/<slice>_vN.py`.

- Are the **only** way one slice interacts with another.

- Provide **keyword-only, typed** functions that:
  
  - Do **shape checks only** (e.g. ULID length, non-empty strings, ints ≥ 0) via `_require_*` helpers.
  
  - Call into the owning slice’s `services.py` module.
  
  - Catch all exceptions and wrap them in a canonical `ContractError`.

### DTOs

- DTOs never contain PII; they pass identifiers (ULIDs) and domain labels only.

- DTOs are simple PII-free shapes used across slice boundaries.

- In contracts (`*_vN.py`), prefer `TypedDict` DTOs (easy to JSON-ify).

- Inside slices (services), dataclasses are fine for internal structures.

### Canonical `ContractError`

- Single canonical type in `app/extensions/errors.py`:
  
  - `code` – stable error category (`bad_argument`, `not_found`, `permission_denied`, `internal_error`, etc.).
  
  - `where` – contract function name (`"finance_v2.log_expense"`).
  
  - `message` – human-readable clue for logs/clients.
  
  - `http_status` – recommended HTTP code.
  
  - `data` – optional structured details (never PII).

- Each contract defines `_as_contract_error(where, exc)` that:
  
  - Passes through existing `ContractError`.
  
  - Maps `ValueError` → `code="bad_argument"`.
  
  - Maps `LookupError` → `code="not_found"`.
  
  - Maps `PermissionError` → `code="permission_denied"`.
  
  - Everything else → `code="internal_error"` with minimal `data`.

### Services

- Live in `app/slices/<slice>/services.py`.

- Do all the real work:
  
  - DB reads/writes.
  
  - Policy lookups (via Governance semantics API).
  
  - Event emission (via `event_bus.emit`).

- Raise **only** “normal” Python exceptions:
  
  - `ValueError` for bad arguments/illegal state.
  
  - `LookupError` when things aren’t found.
  
  - `PermissionError` for policy denials (when enforced in the slice).
  
  - Optionally slice-local domain exceptions (never `ContractError`).

- Contracts wrap these into `ContractError`; services never raise `ContractError` themselves.

- ## Canonical layout for service modules
  
  Use these section headers in this order.
  
  (Resources & Sponsors used in this example):
  
  1. **Module contract + imports**
  
  2. **Constants & conventions**
  
  3. **Policy access wrappers**
  
  4. **Error normalization**
  
  5. **Generic validators (pure)**
  
  6. **History helpers (latest snapshot, next version)**
  
  7. **POC wrappers (thin wrappers over app.services.poc)**
  
  8. **Read-only queries (view/search/list)**
  
  9. **Commands (mutations): ensure/create, set readiness/mou, capability upsert/patch**
  
  10. **(Sponsors-only) Pledges**
  
  11. **(Sponsors-only) Prospect realizations**
  
  12. **(Optional) cross-slice integration verbs (allocation→finance)**
  
  13. **Dev-only helpers**

---

## Events & Observability

### Event Bus

- All slices use a shared `event_bus.emit(...)` helper.

- Emitted events are:
  
  - PII-free.
  
  - Include `domain`, `operation`, `entity_ulid`, `actor_ulid`, `metadata`.

- Ledger subscribes (or is written synchronously for now) to record:
  
  - Who did what, when, to which ULID(s).
    
    ```python
    domain: str,                               # owning slice / domain
    operation: str,                            # what happened
    request_id: str,                           # request ULID
    actor_ulid: Optional[str],                 # who acted (ULID | None)
    target_ulid: Optional[str],                # primary subject | N/A
    refs: Optional[Dict[str, Any]] = None,     # small reference dictionary
    changed: Optional[Dict[str, Any]] = None,  # small “before/after” hints
    meta: Optional[Dict[str, Any]] = None,     # tiny extra context (PII-free)
    happened_at_utc: Optional[str] = None,     # ISO-8601 Z
    chain_key: Optional[str] = None,           # alternate chain (rare)
    ```

### Ledger

- Canonical system-wide log of actions:
  
  - Append-only, no updates/deletes.
  
  - Hash-chained records for tamper detection.

- Stores:
  
  - Event type (`finance.journal.posted`, `governance.policy.updated`, etc.).
  
  - Timestamps (UTC, ISO-8601 Z).
  
  - Actor ULID, target ULID(s), and any correlations (request IDs).
  
  - No PII; only IDs and codes.

---

## Governance Policy

- All Governance policies are stored as **JSON files** under `slices/governance/data/`.

- Each policy file has a corresponding **JSON Schema** that defines its shape.

- `policy_semantics.py` is the single entry point for:
  
  - Loading policy files.
  
  - Validating against schema.
  
  - Providing high-level helpers (`fund_archetypes`, `project_types`, `journal_flags`, budget caps, etc.).

- Only the **Admin slice** (and its contracts) may change policy:
  
  - Admin UI must validate policy JSON against schema and semantics.
  
  - All policy changes are recorded in Ledger via events such as `governance.policy.updated`.

---

## Pinned: Money Flow Invariants

1. **Sponsors is inbound-only.**
   
   - Sponsors **never spends**.
   
   - Sponsors **only**:
     
     - Knows who sponsors are.
     
     - Manages FundingProspects / pledges / CRM.
     
     - Initiates and records **donations** (cash and in-kind).
   
   - Any money “movement” Sponsors triggers is:
     
     - A **donation into Finance**, not an expense.
     
     - Optionally followed by updating its own FundingProspects.

2. **Calendar Projects are the only thing that spends.**
   
   - Outbound money is **always** tied to a `Calendar.Project` (and usually a Task).
   
   - Only Calendar (plus maybe Admin/CLI tools) calls:
     
     - `finance_v2.log_expense(...)`.
   
   - “Sponsor Development” is just another **Calendar Project** with Tasks that log expenses via Finance.

3. **Finance is the bookkeeper, not the decider.**
   
   - Finance:
     
     - Logs **donations** (income) via `log_donation`.
     
     - Logs **expenses** (outbound) via `log_expense`.
     
     - Maintains journal, balances, and reporting.
   
   - Finance does **not** decide:
     
     - Which projects get funded.
     
     - Whether a spend is allowed — it enforces decisions made by Governance + Calendar.

4. **Governance owns policy, not money.**
   
   - Governance:
     
     - Defines `fund_archetypes`, `project_types`, `journal_flags`, budgets, caps, restrictions.
     
     - Evaluates **proposed actions**:
       
       - `evaluate_donation(...)` for inbound.
       
       - `evaluate_expense(...)` / budget checks for outbound.
   
   - Governance **does not** write Finance rows; it returns decisions (DTOs) that Finance/Calendar carry out.

---

## Pinned: Two One-Way Pipelines

### Inbound (donations)

**Sponsors → Governance → Finance → Sponsors (prospect update)**

- Sponsors:
  
  - Calls `governance_v2.evaluate_donation(...)` to validate fund archetype, flags, and any sponsor-specific rules.
  
  - If OK, calls `finance_v2.log_donation(...)` to post a **Journal income** entry:
    
    - `sponsor_ulid`, `fund_id`, `happened_at_utc`, `amount_cents`, flags.
  
  - Optionally calls `sponsors_v2.record_prospect_realization(...)`:
    
    - Updates FundingProspect.realized totals (no money moved; CRM bookkeeping).

- No expenses.

- No `project_id` involved.

- Purely money **coming in** and adjusting Sponsor-side expectations.

- No `project_id` in inbound donations. If you see a donation tied to a project, something went wrong.

### Outbound (spend)

**Calendar → Governance → Finance**

- Calendar:
  
  - A Project/Task needs money to execute.
  
  - Calls `governance_v2.evaluate_expense(...)` (planned) to check:
    
    - Fund restrictions.
    
    - Budget caps.
    
    - Periods and project types.
  
  - If OK, calls `finance_v2.log_expense(...)` with:
    
    - `fund_id`, `project_id`, `occurred_on`, `vendor`, `amount_cents`, `category`, etc.

- Finance:
  
  - Posts the Journal expense (DR expense, CR cash/bank).
  
  - Updates balances.
  
  - Emits `journal.posted` to Ledger.

- Sponsors is **not** in this loop.

- Spending is always “Calendar Project spends from a Fund,” recorded by Finance, constrained by Governance.

- Any expense without a `project_id` (Calendar Project) is a bug unless it is explicitly whitelisted “overhead” with its own Governance rule.

## Where this leaves us (end-to-end picture)

After having fleshed out the basics of Calendar/Project/Governance/Finance food chain:

With these bits in place, you now have:

- **Calendar v2 contract:**
  
  - `create_project(...) -> ProjectDTO`
  
  - `add_project_funding_plan(...) -> ProjectFundingPlanDTO`
  
  - `list_project_funding_plans(project_ulid) -> list[ProjectFundingPlanDTO]`
  
  - `list_projects_for_period(period_label) -> list[ProjectDTO]`

- **Calendar services:**
  
  - `create_project(...)` with an event bus emit,
  
  - `create_funding_plan(...)` (from earlier),
  
  - `list_funding_plans_for_project(...)`,
  
  - `list_projects_for_period(...)`.

- **Governance budget service:**
  
  - `compute_budget_demands_for_period(period_label) -> list[ProjectBudgetDemand]`

- **Governance v2 contract:**
  
  - `get_budget_demands_for_period(period_label) -> list[ProjectBudgetDemandDTO]`

Which means, conceptually, you now have:

> Calendar (Project + FundingPlan) → Governance (aggregated budget demand)  
> → (later) Sponsors (fundraising targets)  
> while Finance still owns all real money in/out via Journal.

## Here’s the “what’s still hanging” snapshot, slice by slice.

### MVP vs Post-MVP

### Calendar (MVP)

**Mostly in place this session**

- `Project` + `ProjectDTO` and `calendar_v2.create_project(...)` wired to `services.create_project(...)` with `event_bus.emit`.

- `ProjectFundingPlan` model sketched and service/contract Legos designed:
  
  - `calendar_v2.add_project_funding_plan(...) -> ProjectFundingPlanDTO`
  
  - `calendar_v2.list_project_funding_plans(project_ulid=...)`
  
  - `services.create_funding_plan(...)` + `_funding_plan_view(...)` + `list_funding_plans_for_project(...)`

- `blackout_ok` contract conceptually wired to `calendar.services.is_blackout(...)`.

### Post-MVP

**Left hanging / to-do after MVP core is stable**

- **Period support on Project**:
  
  - Add `period_label` and/or `project_type_key` to `Project` and use it in:
    
    - `calendar_v2.list_projects_for_period(period_label=...)`
    
    - `services.list_projects_for_period(...)` filtering.

- **Tasks**:
  
  - `Task` model (per-project tasks).
  
  - Task services + `calendar_v2` contracts.
  
  - Optional future: per-task spend key (`task_ulid`) alongside `project_id` in Finance.

- **UI**:
  
  - Routes, forms, and pages for creating/editing Projects and FundingPlan rows.

---

## Governance (MVP)

**Mostly in place already (from before + this session)**

- Canonical `ContractError` wrapper and `_require_*` helpers.

- Donation semantics:
  
  - `governance_v2.evaluate_donation(...)`
  
  - `services_budget.classify_donation_intent(...)` using `policy_funding`, `policy_journal_flags`.

**Designed this session but still to implement/wire fully**

- **Budget demand view**:
  
  - `services_budget.ProjectBudgetDemand` dataclass.
  
  - `services_budget.compute_budget_demands_for_period(period_label)`:
    
    - Calls `calendar_v2.list_projects_for_period(...)`.
    
    - Calls `calendar_v2.list_project_funding_plans(...)`.
    
    - Aggregates `expected_amount_cents` into total/monetary/in-kind/by-fund-archetype.
  
  - `governance_v2.get_budget_demands_for_period(period_label) -> list[ProjectBudgetDemandDTO]` contract wrapper.

### Post-MVP

**Still deliberately tabled**

- **Project precedence / mission alignment**:
  
  - Ranking projects by mission fit, urgency, etc.

- **Fund allocation decisions**:
  
  - Governance-side logic for “this fund archetype + period_label + project_type gets X budget”.

- **Budget caps enforcement surfaces for Finance**:
  
  - Clean Governance API(s) Finance can call to ask:
    
    - “Is this spend allowed from fund F to project P in period T?”
    
    - “What’s the cap/remaining budget?”

- **Policy editing pipeline**:
  
  - Governance Admin contract(s) that replace any lingering devtools references.
  
  - JSON schema validation + semantic checks on save (for policy_* files).

---

## Finance (MVP)

**Legos we actually shaped this session**

- **Error/contract pattern**:
  
  - Consistent `ContractError` wrapper (`_as_contract_error`) and `_require_*` helpers in `finance_v2`.

- **Inbound money (donations)**:
  
  - `finance_v2.log_donation(...) -> DonationDTO`:
    
    - Typed args + basic shape checks.
    
    - Delegates to `services.log_donation(payload, dry_run=...)`.
  
  - `services.log_donation(...)`:
    
    - Validates required payload fields.
    
    - Builds balanced Journal lines (cash/bank vs revenue).
    
    - Calls `post_journal(...)` (which handles `event_bus.emit`).

- **Outbound money (expenses)**:
  
  - `finance_v2.log_expense(...) -> ExpenseDTO`:
    
    - Typed args + shape checks + contract error wrapping.
  
  - `services.log_expense(payload, dry_run=...)`:
    
    - Validates required fields.
    
    - Builds DR expense / CR cash Journal lines.
    
    - Calls `post_journal(...)`.

So: **basic money-in/money-out Legos** are in place, but **policy-blind** for now.

### Post-MVP

**Finance pieces intentionally left for post-MVP or later**

- Hooking `log_donation` into:
  
  - `governance_v2.evaluate_donation(...)` (classification, flags, fund archetype sanity).
  
  - Sponsors FundingProspect realization in a systematic way (beyond the simple `record_prospect_realization` helper).

- Hooking `log_expense` into:
  
  - Governance budget caps and fund restrictions (allowed/not allowed / needs override).
  
  - Approvals / “approved_by_ulid” semantics.

- All the other Finance contracts/services we listed but didn’t Lego-ize yet:
  
  - `record_receipt(...) -> ReceiptDTO`
  
  - `create_fund(...) -> FundDTO`
  
  - `transfer(...)`
  
  - `create_grant(...) -> GrantDTO`
  
  - `set_budget(...) -> BudgetDTO`
  
  - `prepare_grant_report(...)`
  
  - `submit_reimbursement(...) -> ReimbursementDTO`
  
  - `mark_disbursed(...) -> ReimbursementDTO`
  
  - `statement_of_activities(...) -> ActivitiesReportDTO` (read-side).

- In-kind flow:
  
  - `record_inkind(...)` vs `log_donation(...)` and how they’re reported together.

- Any real **Finance UI** or Admin tooling around these flows.

---

## Sponsors (MVP)

**Re-affirmed this session**

- Sponsors is **inbound-only**:
  
  - Sponsors never spends, never owns allocations.
  
  - It owns Sponsors, FundingProspects, and “what have we brought in / realized”.

**Basic helper already in motion**

- `sponsors_v2.record_prospect_realization(...)` concept:
  
  - Called after a donation is logged in Finance to increment a prospect’s realized amount.

### Post-MVP

**Sponsors pieces deliberately deferred**

- A proper Sponsors **read-side over Governance budget demands**:
  
  - `sponsors_v2.get_fundraising_targets(period_label)` built on  
    `governance_v2.get_budget_demands_for_period(...)` + sponsor capabilities.

- A full FundingProspect lifecycle:
  
  - Creation, update, expected vs realized, project-specific targeting, etc.

- Sponsor Development “project” flows:
  
  - Sponsor work as Calendar Projects that spend money (via Finance) to cultivate donors.

- Any UI / reports for “coverage vs demand” (“how much of 2026 needs are covered?”).

- Project precedence & mission alignment.

- Budget caps enforcement for expenses.

- Full reimbursement/grant lifecycle.

- Tasks, per-task spending, and full Calendar PM.

- Admin policy-edit UI suite.

---

## Cross-cutting stuff we know is still ahead

- **UI routes/forms/templates** across slices (Auth/Admin, Calendar, Finance, Sponsors, Governance).

- **Tests and CLI dev flows**:
  
  - Seed scenarios (Projects + FundingPlans + Donations + Expenses).
  
  - Contract tests for the new finance_v2, calendar_v2, governance_v2 endpoints.

- **Admin policy edit suite**:
  
  - Governance Admin replacing devtools for policy_* editing and validation.

- **More rigorous event_bus + ledger integration**:
  
  - Making sure every significant mutation is paireMaking sure every significant mutation is paireMaking sure every significant mutation is paireMaking sure every significant mutation is paired with the right event in the Ledger slice.

---

> We now have the **bones** of: Calendar Projects + anticipated funding (ProjectFundingPlan), Finance money-in/money-out contracts, and a Governance view that *will* see planned budget demand — but actual **budget caps**, **precedence**, **approvals**, and **fundraising targeting** are still intentionally parked for the next passes.

---

## Industrial Lego Pattern (How to Build New Flows)

**Industrial Legos = Contracts ⇄ Services ⇄ Forms ⇄ Routes ⇄ Templates**

For any new flow (e.g. project budget planning, receipt submission, reimbursement), we follow the same pattern:

1. **Define DTOs** in the relevant `*_vN.py`.

2. **Service Lego** in the slice:
   
   - A `services.py` function that:
     - Accepts typed args or a well-documented `payload: dict`.
     - Uses the slice’s models and policies.
     - Emits events via `event_bus`.
     - Returns a DTO.
     - Raises only Python exceptions (no `ContractError`).

3. **Contract Lego** in Extensions:
   
   - Keyword-only, typed args.
   - Uses `_require_*` helpers for shape checking.
   - Calls the service.
   - Wraps any exceptions into a canonical `ContractError` via `_as_contract_error`.

4. **No slice ever bypasses another slice’s contract**:
   
   - No direct imports of another slice’s `services` or `models`.
   - All cross-slice work goes through DTO-shaped contracts.

5. **Form Lego**
   
   - A mutating UI flow is composed of:
     - Contract: takes typed args, returns DTO, throws ContractError.
     - Service: does the DB work and calls event_bus.emit.
   - Form class (WTForms):
     - Fields and validators mirroring the contract’s shape.
     - populate_obj / from_dto helpers when editing.
   - Route:
     - GET: fetch DTO (if needed), instantiate form.
     - POST: if form.validate_on_submit(): → build payload → call contract → flash + redirect; else redisplay with errors.
   - Template:
     - Uses shared macros to render fields and errors.
     - No business logic; only calls contracts through the route.

### Summary:

> ### When adding any new operation (cheat sheet)
> 
> 1. Decide the DTO (shape + PII-free).
> 
> 2. Write/extend the **service** in the owning slice:
>    
>    - Pure Python exceptions (`ValueError`, `LookupError`, etc.).
>    
>    - DB + policy logic.
>    
>    - `event_bus.emit`.
> 
> 3. Wrap it with a **contract** (`*_vN.py`):
>    
>    - Typed, keyword-only args.
>    
>    - `_require_*` shape checks.
>    
>    - `try/except` → `_as_contract_error(where, exc)`.
> 
> 4. Only other slices call the **contract**, never the service/model.

---

## Guardrails (Bugs by Definition)

### These are “if this happens, something went wrong” rules:

- **If Sponsors ever:**
  
  - Calls `finance_v2.log_expense(...)`, or
  
  - References a `project_id` in a write operation  
    → **bug**: Sponsors is trying to spend.

- **If a slice ever:**
  
  - Writes directly to Finance tables without going through Finance services, or
  
  - Edits policy JSON without going through Admin/Governance contracts  
    → **bug**: Boundary violation.

- **If outbound spending happens without:**
  
  - A `Calendar.Project` ULID, and
  
  - A corresponding entry in Finance Journal  
    → **bug**: Money flow is not tied to operations.

Going forward...
---

**Every new Lego (contract/service/DTO) should be checked against this Ethos before it lands.**

### Mental checklist for a new Lego

Finance slice as an example:

Any time you add a new finance operation, you can follow this exact pattern:

1. **Decide the DTO:**
   
   - “What PII-free fields do I want to return?”
   - “What arguments should the caller supply?”

2. **Write the contract function (*finance_v2.*):**
   
   - Typed args only.
   - `_require_str` / `_require_ulid` / `_require_int_ge for shape`.

3. **Build a payload dict:**
   
   - `try: svc.do_the_thing(payload) …`
   - `except Exception as exc: raise _as_contract_error(where, exc).`

4. **Write (or stub) the service (*finance.services.*):**
   
   - Accept that payload dict.
   - Implement the behaviour (or raise NotImplementedError for now).
   - Raise plain exceptions.

5. **Return the DTO the contract promised.**

Do that consistently and the whole app really does become Industrial Legos:
same studs, same dimensions, they just plug into different slices.
