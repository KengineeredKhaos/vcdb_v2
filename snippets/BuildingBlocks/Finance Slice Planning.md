# Finance Slice Planning

If we plan Finance now—clean separations, contracts, and projections—you’ll avoid years of “patch & stitch.” Here’s a lean blueprint that fits our ethos (skinny routes, fat services; slices own data; Extensions-only bridge; ULID everywhere; UTC Z; nothing deleted—only archived).

## What Finance slice is (and isn’t)

- **Is**: a formal accounting sub-ledger with chart of accounts (CoA), funds/grants/budgets, encumbrances, postings, and read-side projections (burn rate, shortfall, balances).

- **Isn’t**: a replacement for general ledgers like QuickBooks; it’s a clean domain that can export to them and reconcile against them.

## Core data model (slice-owned)

- **accounts** (CoA)
  
  - `account_ulid (PK)`, `code`, `name`, `type` (Asset/Liability/NetAsset/Income/Expense), `is_active`

- **funds** (internally: grants are funds with constraints)
  
  - `fund_ulid (PK)`, `name`, `restricted` (bool), `start_at`, `end_at`, `allowed_categories[]` (JSON), `sponsor_ulid?`

- **budgets**
  
  - `budget_ulid`, `fund_ulid`, `account_ulid`, `amount`, `fiscal_period` (month or quarter), `version`

- **encumbrances** (committed but not yet spent)
  
  - `enc_ulid`, `fund_ulid`, `account_ulid`, `amount`, `source_ref` (PO/event id), `status`

- **journals** / **postings** (double-entry)
  
  - `journal_ulid`, `occurred_at`, `memo`, `origin` (slice/domain)
  
  - `postings`: `posting_ulid`, `journal_ulid`, `account_ulid`, `fund_ulid?`, `debit`, `credit`

- **valuation_in_kind**
  
  - `vik_ulid`, `sponsor_ulid`, `description`, `qty`, `fmv_per_unit`, `total_fmv`, `occurred_at`, `source_ref`

All rows have `created_at`, `updated_at`, `is_archived`, and are cross-linked to the **Ledger** via `event_ulid` (1..n events per logical action). No PII stored here.

## Where other slices plug in

- **Sponsors** → in-kind “offer/receipt” events → **Finance** records valuation and a double-entry journal (Debit: In-Kind Expense, Credit: In-Kind Contribution).

- **Logistics/Inventory** → issues/receipts → optional encumbrances & COGS postings.

- **Calendar** → event budgets/actuals → postings by fund.

- **Governance** → policy: allowed categories per fund/grant, retention, close periods, FX/locale.

- **Auth** → RBAC for who may post/void/close.

## Contracts (Extensions)

Versioned, read/write separated; JSON Schema-backed.

*Read*

- `finance_v1.get_fund_balances(filters)` → `{ fund_ulid, available, encumbered, actual_spent, as_of }`

- `finance_v1.get_burn_rate(fund_ulid, horizon_days)` → `{ daily_burn, runway_days, projected_shortfall? }`

- `finance_v1.get_account_activity(account_ulid, range)` → list of `{ occurred_at, memo, debit, credit, balance }`

- `finance_v1.get_grant_summary(fund_ulid)` → `{ budget_total, actual_total, variance, end_at }`

*Write*

- `finance_v1.post_journal(dto)` (strict double-entry)

- `finance_v1.record_in_kind(dto)` (creates valuation + journal + ledger event)

- `finance_v1.create_encumbrance(dto)` / `release_encumbrance(dto)`

- `finance_v1.import_budget(dto)` (idempotent by `correlation_id`)

*Error surface*

- `ContractValidationError` (schema)

- `ContractDataNotFound`

- `ContractConflictError` (e.g., period closed, unbalanced journal, fund not allowed for account)

## DTO sketches (concise)

- **Journal**
  
  ```json
  {
    "journal_ulid": "ULID", "occurred_at": "2025-10-01T00:00:00Z",
    "memo": "String", "origin": "sponsors",
    "lines": [
      { "account_code": "5100", "fund_ulid": "ULID", "debit": 250.00, "credit": 0 },
      { "account_code": "4100", "fund_ulid": "ULID", "debit": 0, "credit": 250.00 }
    ],
    "correlation_id": "ULID"
  }
  ```

- **In-Kind**
  
  ```json
  {
    "sponsor_ulid":"ULID","description":"Winter coats",
    "qty":100,"fmv_per_unit":25.0,"occurred_at":"2025-10-01T00:00:00Z",
    "expense_account":"5200","contrib_account":"4200",
    "fund_ulid":"ULID","correlation_id":"ULID"
  }
  ```

## Projections (read-side tables; recomputable)

- **fund_balance_projection**: `{ fund_ulid, as_of, budgeted, encumbered, actual, available }`

- **burn_rate_projection**: rolling 30/60/90-day average by fund/account.

- **account_trial_balance**: by fiscal period, checkpointed at close.  
  Each carries `{ schema_version, last_event_ulid, rebuilt_at }`.

## Burn rate & shortfall logic (MVP)

- Daily burn = avg of trailing N days (configurable).

- Runway = `available / daily_burn` (guard zero/near-zero).

- Shortfall date = `today + runway_days`; attach confidence band (std dev) optionally.

## Period close & reconciliation

- Governance policy defines **close schedule** (e.g., monthly).

- Once closed: postings in that period are blocked; only correcting entries to a new period (ledger logs both).

- Optional export contract: `finance_v1.export_trial_balance(period)` for QB/ERP; add `reconciliation_status` and a hash of export.

## Why double-entry if we already have Ledger?

- **Ledger** = append-only audit/event spine across all slices.

- **Finance** = accounting semantics (balanced postings, trial balances, budgets).  
  We emit a ledger event per Finance act (`finance.journal.posted`, `finance.encumbrance.created`, etc.), linking ULIDs both ways.

## Incremental path (low-risk)

1. **Schemas & contracts only**: CoA, funds, journals, in-kind DTOs (read+write).

2. **Minimal models** + write paths: journals, valuations (encumbrances can wait).

3. **Projections**: fund balances and basic burn-rate; one cron to recompute nightly, plus incremental updates on write.

4. **UI**:
   
   - In-kind intake (from Sponsor record)
   
   - Fund dashboard (budget vs. actual, burn, runway)
   
   - Journal post (admin-only, with guardrails)

5. **Governance policies**: allowed accounts by fund; period close windows; retention.

## Where to relocate existing things

- **In-kind valuation**: migrate from Sponsors to Finance (Sponsors still initiates; Finance records value + journal).

- **Grant spend tracking**: move out of Transactions; model as `funds + budgets + postings`.

- **“Transactions” slice**: repurpose to “Procurement” later or retire; ledger already centralizes events.

## Guardrails to bake now

- All **Finance write contracts** enforce: balanced lines, allowed fund/account combos, fund active and within date window, period not closed.

- Every write includes `correlation_id` to ensure idempotency.

- Everything emits **ledger events** with `domain=finance`, `operation=journal.posted|vik.recorded|...`, linking `actor_ulid`, `target_id?`, and `refs_json` to source docs.

---
