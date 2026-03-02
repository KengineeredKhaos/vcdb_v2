# VCDB_v2 Financial Rubric

---

Below is the **VCDB v2 Money Flow Rubric** in a “pin-and-build-to-this” format. It’s written to be slice-agnostic, with strict ownership boundaries, canonical ULID linkages, and minimal human interaction as a design goal.

---

# VCDB v2 Money Flow (Finance ↔ Governance ↔ Calendar ↔ Sponsors)

## 0) Goal

Make money movement **accurate, repeatable, and auditable** with **minimal human interaction**.

Humans should mainly:

- upload/import bank statements (or connect feeds later),

- attach receipts when needed,

- approve exceptions when Governance demands it,

- request reports (queries).

Everything else is deterministic.

---

## 1) Core Triangle

### Finance = Book of Record (Facts + Mechanics)

Finance records **money facts**:

- journal entries (double-entry)

- reserves & encumbrances (availability facts)

- projections and reports

Finance does **not** decide policy.

### Governance = Rulebook (Taxonomy + Controls)

Governance defines:

- semantic keys/enums (taxonomy)

- constraints & approval rules (controls)

- budgets and authority thresholds

Governance does **not** reference Finance schema or account codes.

### Calendar = Work Orchestrator (Plans + Demands + Execution)

Calendar owns:

- projects/tasks

- “what needs funding” (demands)

- approvals workflow (collecting approvals, recording decision refs)

- execution events that trigger commitments/spend

### Sponsors = Relationship & Intent (Pledges + Donation Metadata)

Sponsors owns:

- prospects, pledges (intent)

- donor designation intent

- “donation received” records (often human-entered or derived)

Sponsors does **not** post accounting mechanics itself—only triggers Finance to do so.

---

## 2) Glossary (Objects you must model explicitly)

### Funding Demand (Calendar-owned)

A **requirement**, not money.

- “Project P needs $X by date D, preferably from fund types A/B.”

### Funding Intent (Sponsors-owned)

A **promise**, not money.

- pledge, prospect, expected amount/date, donor notes.

### Money Fact (Finance-owned)

A real money event:

- deposit received, expense paid, transfer, reconciliation match, etc.

### Reserve (Finance-owned, off-GL)

Funds locked to a demand/project while fundraising or awaiting readiness.

- “set aside while accumulating to threshold”

### Encumbrance (Finance-owned, off-GL)

Approved commitment to spend, not yet spent.

- “approved spend reserved; prevents double booking”

---

## 3) The One Trace Handle

### `funding_demand_ulid` (Calendar creates it)

This is the ULID that can track the entire “food chain.”

Every downstream record should carry one or more of:

- `funding_demand_ulid` (preferred)

- `project_ulid` (required for project reporting)

- `encumbrance_ulid` (ties commitments to expenses)

- `source_ref_ulid` (ties Finance facts back to Sponsors or bank import)

---

## 4) Lifecycle Pipeline (End-to-End)

### Stage A — Demand Creation (Calendar + Governance input)

1. Calendar creates/updates Funding Demand:
   
   - `funding_demand_ulid`, `project_ulid`, `amount_goal_cents`, `deadline`, `eligible_fund_keys` (optional), `status`.

2. Calendar uses Governance *read-only* to validate demand constraints:
   
   - allowed fund archetypes / restriction semantics (no schema coupling).

### Stage B — Demand Publication (Calendar → Sponsors)

3. Calendar marks demand `published`.

4. Sponsors reads published demands (read-only contract) and pursues funding.

### Stage C — Intent Tracking (Sponsors)

5. Sponsors records pledge/prospect linked to `funding_demand_ulid`.

6. No money enters Finance yet.

### Stage D — Receipt of Funds (Sponsors → Finance) OR (Finance bank import)

7. When money is received:
   
   - Sponsors records “donation received” and calls Finance to post income **OR**
   
   - Finance imports bank line and posts/matches with Sponsors record.

8. Finance posts income (GL) and updates availability.

9. If designated to the demand/project, Finance creates/updates a **Reserve**.

### Stage E — Commitments (Calendar → Governance → Finance Encumbrance)

10. Calendar plans spending and requests Governance approval when needed.

11. Governance returns a `decision_ref_ulid` (proof).

12. Calendar calls Finance to create **Encumbrance** against reserved/available funds.

### Stage F — Spending (Calendar → Finance)

13. When the expense occurs:
    
    - Calendar calls Finance to `post_expense(...)`, referencing `encumbrance_ulid` when applicable.

14. Finance posts expense (GL) and relieves encumbrance.

### Stage G — Reporting (Queries, no human accounting)

15. Reports are queries filtered by:
    
    - `funding_demand_ulid`, `project_ulid`, `fund_key`, `expense_kind`, time window.

---

## 5) What Each Slice Supplies (and must NOT supply)

### Governance supplies (read-only contracts)

**Taxonomy**

- `fund_keys`, `fund_archetypes`, `restriction_keys`

- `income_kind`, `expense_kind`

- budget period definitions

**Controls**

- spending caps (e.g. $200 staff cap)

- approval matrices (who approves what)

- budget constraints (caps by period/fund/project class)

**Governance must NOT**

- reference Finance tables/columns

- reference Finance account codes

- prescribe journal line construction

### Calendar supplies

- `project_ulid` (required)

- `funding_demand_ulid` (required for traceability)

- execution timing: `happened_at`, task refs

- `decision_ref_ulid` when Governance approval is required

- receipts/doc refs (pointers/hashes)

**Calendar must NOT**

- post journal mechanics itself

- bypass Governance checks when policy requires approval

### Sponsors supplies

- `payer_entity_ulid` (donor Party/Entity ULID; no PII)

- pledge/prospect records (intent)

- donation metadata: designation intent, restriction intent

- triggers “income received” into Finance OR supports reconciliation matching later

**Sponsors must NOT**

- do accounting line selection

- store ledger-worthy PII

### Finance supplies

- deterministic posting engine (GL)

- reserves/encumbrances (availability facts)

- projections

- query/report surfaces

**Finance must NOT**

- read Governance JSON files directly

- decide whether spending is allowed (only validate inputs)

- require humans to choose accounts per transaction

---

## 6) Canonical Inputs to Finance (high-level DTO shapes)

### `post_income(...)` (called by Sponsors or bank import)

Required:

- `amount_cents`, `received_at_utc`

- `payer_entity_ulid`

- `fund_key`

- `income_kind`

- `source_ref_ulid` + `source_slice` (Sponsors donation ULID or bank txn ULID)

Strongly recommended:

- `funding_demand_ulid` (or at least `project_ulid`)

- `restriction_keys` (if restricted/designated)

- `external_ref` (bank txn id / check number / deposit id)

- `memo`

Behavior:

- posts GL income (cash ↑, revenue ↑)

- updates availability projections

- if designated → creates/updates Reserve

### `reserve_funds(...)` (Finance-owned fact)

Required:

- `funding_demand_ulid`, `project_ulid`

- `amount_cents`

- `fund_key`

- `source_ref_ulid` (often the income journal ULID)

Behavior:

- reduces “available general funds”

- increases “reserved for demand/project”

### `encumber_funds(...)` (called by Calendar)

Required:

- `funding_demand_ulid`, `project_ulid`

- `amount_cents`, `fund_key`

- `decision_ref_ulid` (when policy requires it)

Behavior:

- moves from “available/reserved” → “encumbered”

- does not touch cash (off-GL)

### `post_expense(...)` (called by Calendar)

Required:

- `amount_cents`, `happened_at_utc`

- `project_ulid`, `funding_demand_ulid`

- `expense_kind`, `fund_key`

- `source_ref_ulid` (Calendar task/payment ULID)

Recommended:

- `encumbrance_ulid`

- `external_ref` (card txn id), `receipt_ref`

Behavior:

- posts GL expense (expense ↑, cash ↓ or payable ↑)

- relieves encumbrance (full/partial)

- updates projections

---

## 7) Accounting Determinism Rule (no humans picking accounts)

Finance owns the mapping:

- `expense_kind → expense_account_code`

- `income_kind → revenue_account_code`

- “cash/bank account” selection strategy (configurable but Finance-owned)

Governance never references account codes.

---

## 8) Automation Rule (minimize human interaction)

### Default modes

- Sponsors records donation received → Finance auto-posts.

- Finance bank import creates bank txn facts → auto-match to Sponsors donation or Calendar expense.

- Unmatched lines → exceptions queue (Admin/Staff resolves).

Humans handle exceptions, not routine bookkeeping.

---

## 9) Boundary Leak Tests (quick sanity checks)

If any answer is “yes,” you’ve violated the rubric:

1. “If I rename a Finance table/column, must Governance policy change?”

2. “If I change account codes, must Governance policy change?”

3. “Can Calendar post a journal entry without Finance?”

4. “Can Sponsors post accounting line details (debit/credit accounts)?”

---

## 10) Reporting Guarantees (the whole point)

You should always be able to query:

- By `funding_demand_ulid`: pledged, received, reserved, encumbered, spent, remaining.

- By `project_ulid`: same, plus spending breakdown by `expense_kind`.

- By `fund_key` / `restriction_keys`: compliance and usage.

- By time window: monthly/quarterly/yearly statements.



---

# Man-splained for "Tards" like me

## 1) The three kinds of “money objects” you need

### A) Funding Demand (Calendar-owned)

This is *not money*. It’s a **requirement**.

Think: “Project P needs $3,500 to execute. Ideally from fund types X/Y, by date D.”

- Owned by **Calendar** because Calendar owns projects/tasks and execution planning.

- Governance influences it (caps, allowed fund types), but Governance doesn’t create it.

### B) Funding Intent (Sponsors-owned)

This is also *not money*. It’s **a promise**.

Think: pledge, prospect, “we think the Elks will fund $400 kits.”

- Owned by **Sponsors** (relationships and commitments).

### C) Money Fact (Finance-owned)

This is real money movement and its accounting record.

Think: deposit received, expense paid, bank line imported, journal posted.

- Owned by **Finance** (book of record).

**Encumbrances/reserves live here too**, because they’re “availability facts” even when cash hasn’t moved.

---

## 2) The one ULID that can track the whole chain

Yes: if we attach a ULID to the demand, you can track the entire food chain.

Call it:

### `funding_demand_ulid` (Calendar creates it)

Then every downstream object stores a reference to it:

- Sponsors pledge / donation: `funding_demand_ulid`

- Finance income journal: `funding_demand_ulid` (or project_ulid if demand omitted)

- Finance reserve/encumbrance: `funding_demand_ulid`

- Finance expenses: `funding_demand_ulid` (and/or encumbrance_ulid)

That ULID becomes your “project money trace ID.”

---

## 3) Big-picture pipeline (end-to-end)

Here’s the flow you asked for, in the order it actually happens:

```
Calendar (need) → Sponsors (raise/track intent) → Finance (record cash)
Calendar (execute) → Finance (encumber + spend) → Reports (query by ULIDs)
```

Let’s zoom into each stage.

---

## 4) Stage 1 — Funding demands are generated (Calendar + Governance)

### Who generates the demand?

**Calendar.** Because Calendar owns “work to be done” and the plan.

Calendar creates a Funding Demand when:

- a project is created (initial budget)

- a project plan is revised (delta demand)

- a task bundle is added (“we need $X for this phase”)

### What role does Governance play?

Governance does **not** author demands. Governance supplies:

- budget period definitions (monthly/annual rules)

- spending authority rules (staff cap, approval needs)

- fund restriction taxonomy keys

- “allowed fund archetypes” and constraint semantics

Calendar uses those rules to *compute or validate* a demand.

**Governance answers questions like:**

- “Can this project ask for restricted grant money?”

- “Do we require a Treasurer approval to commit above $200?”

- “If funds are local_only, can they fund this project type?”

### What a Funding Demand record should contain (minimum)

- `funding_demand_ulid`

- `project_ulid` (required)

- `title` / “purpose” (for humans)

- `amount_goal_cents`

- `deadline_date` (optional)

- `eligible_fund_keys` or fund archetypes (optional but very useful)

- `status` (draft/published/funded/closed)

- optional “phases” (nice later)

---

## 5) Stage 2 — Funding requirements are “published” (Calendar → Sponsors)

This is purely data exposure.

### Who “publishes”?

Calendar “publishes” by changing demand status to `published` and making it queryable.

### How does Sponsors see it?

Sponsors reads via a **Calendar contract** (read-only), like:

- “list published funding demands”

- “get demand details by ulid”

- “show unmet amount”

Sponsors then uses that to drive:

- prospect list

- pledge tracking

- campaign messaging

**Key point:** Sponsors does not invent the demand amounts. It can propose adjustments, but Calendar is the system of record for “what we need to execute work.”

---

## 6) Stage 3 — Funding intent & fulfillment (Sponsors → Finance)

This splits into two timelines:

### A) Pledge / prospect (intent)

Sponsors records:

- pledge/prospect ULID

- expected amount

- expected date

- links to `funding_demand_ulid` (and/or `project_ulid`)

- designation notes/restrictions

No money enters Finance yet.

### B) Donation received (money fact)

When money is actually received (check, ACH, cash):  
Sponsors records “received” and triggers Finance posting.

#### Sponsors → Finance payload for income should include:

- `amount_cents`

- `received_at`

- `payer_entity_ulid`

- `fund_key` (semantic, Governance-defined)

- `income_kind` (semantic: donation/grant/etc.)

- `funding_demand_ulid` (optional but preferred)

- `project_ulid` (optional; can be derived from demand)

- `restriction_keys` (if donor restricted)

- `external_ref` (check # / bank txn id / deposit slip)

- `source_ref_ulid` (Sponsors donation record ULID)

Finance then:

1. posts the journal entry (cash ↑, revenue ↑)

2. updates availability projections

3. optionally creates/updates a **Reserve** tied to the demand/project

---

## 7) Stage 4 — Reserve vs Encumber: “funds accumulate until we can start”

This is exactly your “set aside temporarily while fundraising” requirement.

### Reserve (Finance-owned)

A Reserve is: “these dollars are locked for this demand/project.”

Finance can create reserves automatically when income is designated.

So now Calendar can ask Finance:

- “How much is reserved for demand D?”

- “Have we met the threshold to begin execution?”

This is how demands become *actionable* without human bookkeeping.

---

## 8) Stage 5 — Realized funding is allocated/encumbered (Calendar → Finance)

Now we’re in “execution mode.”

### When does encumbrance happen?

When Calendar is ready to commit to a spend:

- hire vendor

- order supplies

- schedule service fulfillment

Calendar first obtains Governance approvals if needed:

- “over $200” approvals, restricted fund approvals, etc.

Then Calendar calls Finance:

- “encumber $X for demand D / project P”

- includes `decision_ref_ulid` (proof Governance cleared it)

Finance writes an **Encumbrance** record (not a journal yet), reducing “available” but not changing cash.

**Why encumber?**  
Because it prevents the same reserved dollars from being double-booked for multiple purchases.

---

## 9) Stage 6 — Spending against funds (Calendar → Finance actual expenses)

When the actual purchase happens (or invoice paid):

Calendar calls Finance:

- `post_expense(...)` with
  
  - `amount_cents`
  
  - `expense_kind`
  
  - `project_ulid`
  
  - `funding_demand_ulid`
  
  - `encumbrance_ulid` (if it was reserved/committed earlier)
  
  - `happened_at`
  
  - `receipt_ref` / `external_ref`

Finance:

1. posts journal entry (expense ↑, cash ↓)

2. relieves encumbrance (fully or partially)

3. updates projections

4. emits ledger event

Now reporting becomes trivial:

- demand D: pledged, received, reserved, encumbered, spent, remaining

- project P: same

- expense_kind: same

---

## 10) Who handles what (one page “ownership map”)

### Calendar owns

- Projects/tasks

- Funding demands (`funding_demand_ulid`)

- Publication of demands

- Execution plan, work status

- Approvals workflow orchestration (but Governance decides rules)

### Sponsors owns

- Prospects/pledges

- Donor communications

- Donation/pledge records & metadata (designation intent)

- Triggering “received money” events to Finance (or matching later)

### Finance owns

- Bank truth / journal truth

- Posting engine

- Reserves + encumbrances (availability facts)

- Reports (query by ULIDs and tags)

### Governance owns

- Rules, caps, restriction semantics, approval matrix

- Taxonomy keys that must be consistent across slices

- “preview/decision” outputs, not accounting instructions

---

## 11) The “ULID food-chain trace” you asked for

Yes, in practice you can trace:

- `funding_demand_ulid`
  
  - Sponsors: pledge(s), donation(s)
  
  - Finance: income journal(s)
  
  - Finance: reserve movements (accumulating)
  
  - Finance: encumbrance(s)
  
  - Finance: expense journal(s)
  
  - Finance: reconciliation matches (bank line ULIDs)

That gives you a full audit trail with one handle.

---

## 12) The minimal set of lifecycle states (to reduce opacity)

### Funding Demand (Calendar)

- `draft` → `published` → `funding_in_progress` → `funded` → `executing` → `closed`

### Money availability (Finance computed per demand)

- pledged (Sponsors)

- received (Finance)

- reserved (Finance)

- encumbered (Finance)

- spent (Finance)

- remaining (computed)

This is the dashboard that will make it “not opaque.”

---




