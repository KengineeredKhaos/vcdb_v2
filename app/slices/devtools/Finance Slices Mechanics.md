# Finance Slice Mechanics

# Finance Slice — Static Map

## Purpose

Financial Journal (single source of truth) of all money movement within the application.

Tasks

- Log Income (source: Sponsor slice, optionally CLI tools)
  (all inbound decisions are vetted through Governance policy)
  
  **DATA POINTS:**
  
  - classification (only one per transaction)
    
    - grant (upfront)
    - grant (reimbursable)
    - cash/check
    - in-kind goods/services
  
  - restrictions (zero or more, enforced elsewhere)
    
    - unrestricted
    - veteran-only
    - homeless-only
    - local-only

- Allocation / use of funds (in accordance with Governance policy)

- Expenditure (identified by fund + project, with category and period)

- Period reporting (internal “trial balance” style)

- Grant tracking (promises vs receipts vs reimbursements)

- Permanent, immutable, historical record (Finance doesn’t delete, it posts reversals)

---

## Modules & responsibilities

### `app/slices/finance/models.py`

High-level mental map; see the model docstrings and code for full details.

- `Account`

  - `code: str` — chart of accounts code (e.g. `"1000"` for checking)
  - `name: str` — human readable label
  - `type: str` — assets / liabilities / net_assets / revenue / expense / etc.
  - `active: bool` — soft-flag to hide retired accounts

- `Fund`

  - `id: ULID` — primary key
  - `code: str` — short human code (e.g. `"OPS-2026"`)
  - `name: str` — human label
  - `archetype_key: str` — governance fund archetype key
  - `restriction: str` — internal restriction type:
    - `"unrestricted"`, `"temporarily_restricted"`, `"permanently_restricted"`
  - `starts_on`, `expires_on` — optional date bounds for when the bucket is valid
  - `active: bool` — whether this fund can still be used

- `Project`

  - Finance-local project dimension (label + active flag).
  - The cross-slice “real” project lives in the **Calendar** slice.
  - Journal lines reference a project via:
    - `JournalLine.project_ulid: str | None` — typically a Calendar `Project` ULID.

- `Period`

  - `period_key: str` — e.g. `"2026-03"` (yyyy-MM)
  - `status: str` — `"open" | "soft_closed | "closed"`
    - `open` — normal posting allowed
    - `soft_closed` — normal posting blocked, Admin overrides only
    - `closed` — fully locked (no new activity, only reads / reports)

- `Journal`

  - Header for a posted financial transaction:
    - `ulid` — primary key
    - `source` — origin slice (“finance”, “calendar”, “sponsors”, etc.)
    - `external_ref_ulid` — optional ULID of related entity (allocation, receipt, etc.)
    - `currency` — `"USD"` for MVP
    - `period_key` — derived from `happened_at_utc`
    - `happened_at_utc` — when the transaction occurred
    - `posted_at_utc` — when Finance wrote it
    - `memo`, `created_by_actor`

- `JournalLine`

  - Line-item inside a `Journal`:
    - `journal_ulid` — FK to `Journal`
    - `seq` — line number within the journal
    - `account_code` — chart of accounts code (1000, 4100, 5200, …)
    - `fund_code` — code of `Fund` that this line touches
    - `project_ulid` — ULID of related Calendar Project (or other bucket)
    - `amount_cents: int` — positive or negative; total must net to zero per journal
    - `memo` — optional detail
    - `period_key` — denormalized from parent for fast reporting

- `BalanceMonthly`

  - Pre-aggregated balances per `(period_key, account_code, fund_code)` etc.
  - Updated incrementally by journal posting so most reports don’t have to rescan `JournalLine`.

- `StatMetric`

  - Counts and non-monetary metrics keyed by period & label
  - E.g. “kits_issued”, “clients_served” — Finance-adjacent program stats.

- `Grant`, `Reimbursement`, `Budget`, `BudgetLine`

  - Bookkeeping entities for grant programs, reimbursement requests, and budget caps.
  - They do **not** move money by themselves; they tag and constrain how money moves via Journal entries.

---

### Journal & posting services — `app/slices/finance/services_journal.py`

Core write-path for all money movement.

- `post_journal(...) -> str`

  - Validates a batch of lines (accounts exist, funds exist, sum=0).
  - Derives `period_key` from `happened_at_utc`.
  - Writes `Journal` + `JournalLine` rows.
  - Updates `BalanceMonthly` incrementally.
  - Emits `event_bus.emit(..., chain_key="finance.journal")`.

- `reverse_journal(journal_ulid, created_by_actor) -> str`

  - Reads an existing journal and posts an exact negating reversal.
  - Enforces open period on the original journal’s period.

- `log_donation(payload: dict, dry_run: bool = False) -> DonationDTO`

  - Slice implementation for `finance_v2.log_donation(...)`.
  - Builds a balanced journal (DR cash/bank account, CR revenue account).
  - Enforces that this is **income only** (no `project_id`).
  - Returns a PII-free `DonationDTO` summarising the donation.

- `log_expense(payload: dict, dry_run: bool = False) -> ExpenseDTO`

  - Slice implementation for `finance_v2.log_expense(...)`.
  - Assumes Governance / Calendar have already approved the spend.
  - Builds a balanced journal (DR expense account, CR cash/bank).
  - Requires:
    - `fund_id`, `project_id`, `occurred_on`, `vendor`, `amount_cents`, `category`.
  - Optional:
    - `bank_account_code`, `expense_account_code`, `memo`,
      `external_ref_ulid`, `created_by_actor`, `source`.

- `record_inkind(...)` (planned / stubbed)

  - Will log non-cash in-kind donations as revenue with matching expense,
    so they appear in activity reports while keeping cash unaffected.

- `record_receipt(...) -> ReceiptDTO` (skeleton)

  - Placeholder for logging receipts / documents that back Journal entries.

- `release_restriction(...)` (planned)

  - Internal helper to move amounts from restricted to unrestricted funds
    when Governance policy says restrictions have been satisfied.

- Projection helpers:

  - `_apply_to_balances(...)`
  - `rebuild_balances_for_period(period_key)`
  - `record_stat_metric(...)`

---

### Funds & budgets services — `app/slices/finance/services_funds.py`

Read/write helpers around the **fund dimension** and budget status.

- `create_fund(...) -> FundDTO`

  - Creates a new `Fund` row given `code`, `name`, `archetype_key`, optional start/expiry.
  - Delegates all validation and DB writes; called from `finance_v2.create_fund(...)`.

- `get_fund_summary(fund_id, period_label=None) -> FundDTO`

  - Returns a PII-free snapshot of a single fund:
    - codes, restriction, active flag
    - current balances / activity for the requested period or overall.

- `get_fund_index(period_label=None) -> list[FundDTO]`

  - Returns a list of fund summaries for status dashboards:
    - high-level view: balances, restricted vs unrestricted, activity flags.

- Period helpers:

  - `set_period_status(period_key, status)`
  - `get_or_create_period(period_key)`
  - Used to manage the `"open" / "soft_closed" / "closed"` life-cycle.

- Archetype helpers (planned):

  - `get_fund_archetypes()` for Governance / Admin UIs.

---

### Grants & reimbursements — `app/slices/finance/services_grants.py`

Paper trail for grant programs and reimbursable flows.

- `create_grant(...) -> GrantDTO`

  - Defines a grant program anchored to a `Fund` and Governance archetype.

- `submit_reimbursement(...) -> ReimbursementDTO`

  - Records a reimbursement request to a grant:
    - amount requested
    - related fund / project context
    - documentation status.
  - Does **not** move money; it’s a “paperwork only” entity.

- `mark_disbursed(...) -> ReimbursementDTO`

  - Marks a reimbursement as paid once the sponsor actually sends funds.
  - Actual money movement is logged by calling `log_donation(...)`
    against the appropriate fund.

---

### Reporting — `app/slices/finance/services_report.py`

- `statement_of_activities(period: str) -> ActivitiesReportDTO`
  - Builds a simple Statement of Activities for a given period:
    - Income by category / fund
    - Expenses by category / fund
    - Net change in net assets.
  - Uses `BalanceMonthly` and/or `JournalLine` as needed.

---

### Contracts — `app/extensions/contracts/finance_v2.py`

Thin, versioned wrappers around the slice services; they:

- Validate types (ULIDs, positive ints, non-empty strings).
- Shape inputs to the payloads expected by the services.
- Catch slice errors and re-raise as `ContractError` with stable codes.

Key entrypoints:

- Inbound (donations / receipts)

  - `log_donation(...) -> DonationDTO`
    Called by Sponsors / CLI; posts cash donations into the Journal.

- Outbound (expenses)

  - `preview_expense(...) -> ExpensePreviewDTO`
    Call Governance for a budget/policy decision **without** writing anything.
  - `log_expense(...) -> ExpenseDTO`
    Called after an “OK” decision to actually write the Journal rows.

- Funds

  - `create_fund(...) -> FundDTO`
  - `get_fund_summary(fund_ulid: str) -> FundDTO`
  - `get_fund_index(period_label: str | None = None) -> list[FundDTO]`

- Grants / reimbursements

  - `create_grant(...) -> GrantDTO`
  - `submit_reimbursement(...) -> ReimbursementDTO`
  - `mark_disbursed(...) -> ReimbursementDTO`

- Reporting

  - `statement_of_activities(period: str) -> ActivitiesReportDTO`

For detailed argument semantics, see the docstrings in the corresponding `services_*` modules; the contract docstrings stay intentionally brief.

---

## Contracts (public entrypoints) — snapshot

This is intentionally a **high-level** view; see the service docstrings for the full shapes.

| Contract function                    | Input (typed, high level)                                           | Output DTO            | Called by                  |
| ------------------------------------ | ------------------------------------------------------------------- | --------------------- | -------------------------- |
| `finance_v2.log_donation`            | `sponsor_ulid`, `fund_id`, `happened_at_utc`, `amount_cents`, …     | `DonationDTO`         | Sponsors, Admin/CLI        |
| `finance_v2.preview_expense`         | `fund_id`, `project_id`, `amount_cents`, `fund_archetype_key`, …    | `ExpensePreviewDTO`   | Calendar, Admin tools      |
| `finance_v2.log_expense`             | `fund_id`, `project_id`, `occurred_on`, `vendor`, `amount_cents`, … | `ExpenseDTO`          | Calendar, Admin/CLI        |
| `finance_v2.get_fund_summary`        | `fund_ulid`, optional `period_label`                                | `FundDTO`             | Admin, Reports, Governance |
| `finance_v2.get_fund_index`          | optional `period_label`                                             | `list[FundDTO]`       | Admin, Reports             |
| `finance_v2.statement_of_activities` | `period` (e.g. `"2026-03"`)                                         | `ActivitiesReportDTO` | Admin, Board/Reports       |

---

## 1. High-level Chart of Accounts structure

(unchanged, still correct)

We’ll stick to a simple nonprofit structure:

- **1000–1999**: Assets (what we own)
- **2000–2999**: Liabilities (what we owe)
- **3000–3999**: Net Assets (what’s left over, unrestricted vs restricted)
- **4000–4999**: Revenue (money / value coming in)
- **5000–5999**: Expenses – Program (doing the mission)
- **6000–6999**: Expenses – Management & General (admin)
- **7000–7999**: Expenses – Fundraising

In VCDB:

- `JournalLine.account_code` uses **these codes**.
- `Fund` / `Grant` / `Project` / `Sponsor` are **dimensions** layered *on top* of these accounts, not new account codes.

COA: dict[str, dict[str, str]] = {
    # --------
    # ASSETS
    # --------
    "cash_operating": {"code": "1000", "name": "Cash - Operating Bank", "type": "asset"},
    "petty_cash":     {"code": "1010", "name": "Petty Cash", "type": "asset"},

    "recv_grants_contrib": {"code": "1100", "name": "Grants & Contributions Receivable", "type": "asset"},
    "undeposited_funds":   {"code": "1200", "name": "Undeposited Funds", "type": "asset"},  # optional but handy
    "prepaid_expenses":    {"code": "1300", "name": "Prepaid Expenses", "type": "asset"},

    "fixed_assets":        {"code": "1500", "name": "Fixed Assets", "type": "asset"},
    "accum_depr":          {"code": "1590", "name": "Accumulated Depreciation", "type": "asset"},  # contra-asset

    # -------------
    # LIABILITIES
    # -------------
    "accounts_payable": {"code": "2000", "name": "Accounts Payable", "type": "liability"},
    "accrued_liab":     {"code": "2100", "name": "Accrued Liabilities", "type": "liability"},
    "refundable_adv":   {"code": "2200", "name": "Refundable Advances / Deferred Revenue", "type": "liability"},

    # -----------
    # NET ASSETS
    # -----------
    "na_without_dr": {"code": "3000", "name": "Net Assets Without Donor Restrictions", "type": "net_assets"},
    "na_with_dr":    {"code": "3100", "name": "Net Assets With Donor Restrictions", "type": "net_assets"},

    # --------
    # REVENUE
    # --------
    "contrib_revenue":   {"code": "4000", "name": "Contributions", "type": "revenue"},
    "grant_revenue":     {"code": "4100", "name": "Grant Revenue", "type": "revenue"},
    "program_rev":       {"code": "4200", "name": "Program Service Revenue", "type": "revenue"},
    "event_rev":         {"code": "4300", "name": "Fundraising Event Revenue", "type": "revenue"},
    "merch_rev":         {"code": "4400", "name": "Merchandise Sales", "type": "revenue"},
    "inkind_revenue":    {"code": "4500", "name": "In-Kind Contributions", "type": "revenue"},
    "other_income":      {"code": "4900", "name": "Other Income", "type": "revenue"},

    # ---------
    # EXPENSES (NATURAL)
    # ---------
    "direct_program_costs": {"code": "5000", "name": "Direct Program Costs", "type": "expense"},
    "supplies":             {"code": "5100", "name": "Supplies", "type": "expense"},
    "occupancy":            {"code": "5200", "name": "Occupancy (Rent & Utilities)", "type": "expense"},
    "insurance":            {"code": "5300", "name": "Insurance", "type": "expense"},
    "professional_fees":    {"code": "5400", "name": "Professional Fees", "type": "expense"},
    "software_it":          {"code": "5500", "name": "Software & IT", "type": "expense"},
    "postage_shipping":     {"code": "5600", "name": "Postage, Freight & Shipping", "type": "expense"},
    "travel_meetings":      {"code": "5700", "name": "Travel & Meetings", "type": "expense"},
    "marketing_cultivation":{"code": "5800", "name": "Marketing / Donor & Sponsor Cultivation", "type": "expense"},
    "event_expenses":       {"code": "5900", "name": "Event Expenses", "type": "expense"},
    "bank_merchant_fees":   {"code": "5950", "name": "Bank & Merchant Processing Fees", "type": "expense"},
    "cogs":                 {"code": "6000", "name": "Cost of Goods Sold", "type": "expense"},
    "depreciation":         {"code": "6100", "name": "Depreciation Expense", "type": "expense"},
    "other_expense":        {"code": "6900", "name": "Other Expense", "type": "expense"},
}


---


