# Finance Slices Mechanics

# Finance Slice — Static Map

## Purpose

Financial Journal (single source of truth) of all money movement within the application.

Tasks

- Log Income (source: Sponsor slice)
  (this is all vetted through Governance Policy)
  
  **DATA POINTS:**
  
  - classification (only one per transaction)
    
    (additional transactions required per classification from same donor/event )
    
    - grant (upfront)
      
      - reporting requirements
    
    - grant (reimburseable)
      
      - reporting requirements
    
    - cash/check
    
    - in-kind goods/services
  
  - Restrictions (one or many)
    
    - unrestricted
    
    - veteran-only
    
    - homeless-only
    
    - local-only

- allocation (in accordance with Governance policy)

- expenditure (identified by project, by class, by fund)

- period reporting

- grant tracking

- permanent, immutable, historical record

## Modules & Responsibilities

- `app/slices/finance/models.py`
  - `Account`
    - code: str
    - name: str
    - type: str
    - active: bool
  - `Fund`
    - code: str
    - name: str
    - restriction: mapped (unrestricted|temp|perm)
    - active: bool
  - `Project`
    - project_ulid that belongs to Calendar
    - This is a planning & tracking tool
  - `Period`
    - period_key: str
    - status: str (open|soft_close|closed)
  - `Journal`
  - `JournalLine`
  - `BalanceMonthly`
  - `StatMetric`
  - (whatever else you actually have)
- `app/slices/finance/services.py`
  - `log_expense(payload, dry_run=False) -> ExpenseDTO`
  - `record_inkind(...)`
  - `post_journal(...)`
  - etc.
- `app/extensions/contracts/finance_v2.py`
  - `log_expense(...) -> ExpenseDTO`
  - `log_donation(...) -> DonationDTO` (planned)
  - `get_fund_summary(...) -> FundSummaryDTO`
  - etc.

## Contracts (public entrypoints)

| Contract function             | Input (typed)                        | Output DTO       | Called by      |
| ----------------------------- | ------------------------------------ | ---------------- | -------------- |
| `finance_v2.log_expense`      | fund_id, project_id, amount_cents, … | `ExpenseDTO`     | Calendar, CLI  |
| `finance_v2.log_donation`     | sponsor_id, fund_archetype_key, …    | `DonationDTO`    | Sponsors, CLI  |
| `finance_v2.get_fund_summary` | fund_id, period_key                  | `FundSummaryDTO` | Admin, Reports |

## 1. High-level Chart of Accounts structure

We’ll stick to a simple nonprofit structure:

- **1000–1999**: Assets (what we own)

- **2000–2999**: Liabilities (what we owe)

- **3000–3999**: Net Assets (what’s left over, unrestricted vs restricted)

- **4000–4999**: Revenue (money / value coming in)

- **5000–5999**: Expenses – Program (doing the mission)

- **6000–6999**: Expenses – Management & General (admin)

- **7000–7999**: Expenses – Fundraising

In VCDB:

- `JournalLine.account_code` will use **these codes**.

- `Fund` / `Grant` / `Project` / `Sponsor` are **dimensions** layered *on top* of these accounts, not new account codes.

---

## 2. Proposed VCDB v2 Chart of Accounts (MVP)

### Assets (1000s) – “What we own”

| Code | Name                          | Purpose / Usage                                                                                                                          |
| ---- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1000 | **Operating Cash – Checking** | Main bank account. All donations & expenses hit here by default. This is the one your current code uses as the default **bank account**. |
| 1010 | Petty Cash                    | Small cash box used for events, petty reimbursements. Optional for MVP.                                                                  |
| 1100 | Grants Receivable             | (Optional) Used if you accrue grants pledged but not yet received. For MVP you can skip and only book cash when received.                |
| 1300 | Prepaid Expenses              | (Optional) Prepaid insurance, rent, etc. Not needed until you go more GAAP-y.                                                            |
| 1400 | Equipment & Fixed Assets      | (Optional) Chairs, tables, tents. Fine to leave this out until you care about capitalizing gear.                                         |

For MVP you can literally start with **just 1000** and add the others as needed.

---

### Liabilities (2000s) – “What we owe”

| Code | Name                        | Purpose / Usage                                                                                                                |
| ---- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 2000 | Accounts Payable            | Bills you owe vendors (if you ever put things on account instead of paying on the spot).                                       |
| 2100 | Accrued Expenses            | (Optional) Things you owe but haven’t received an invoice for.                                                                 |
| 2200 | Deferred Revenue / Advances | (Optional) Money received in advance for a program you haven’t delivered yet. For a simple cash-basis setup you can skip this. |

For VCDB’s first live deployment, you can treat everything as “cash as it hits” and only add these when/if the Treasurer wants proper accrual accounting.

---

### Net Assets (3000s) – “What’s left over”

These accounts usually don’t get hit directly by day-to-day Journal entries; they’re affected when you close the year or reclassify restrictions. But it’s good to name them.

| Code | Name                                     | Purpose / Usage                                                    |
| ---- | ---------------------------------------- | ------------------------------------------------------------------ |
| 3100 | Net Assets – Unrestricted                | General accumulated surplus.                                       |
| 3200 | Net Assets – Temporarily Restricted      | Grants/donations with time/purpose restrictions (until satisfied). |
| 3300 | Net Assets – Permanently Restricted      | True endowments (probably not relevant for you right now).         |
| 3400 | Net Assets – Board Designated (Optional) | Unrestricted funds that the Board has internally earmarked.        |

You don’t need to write entries to these directly in VCDB flows; they’re more for annual closeout.

---

### Revenue (4000s) – “Money / value coming in”

This is where things like `4100` live.

| Code | Name                                 | Purpose / Usage                                                                                                                                            |
| ---- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4100 | **Contributions – Cash Donations**   | General cash donations from individuals / sponsors. This is what `log_donation` uses by default today.                                                     |
| 4110 | Contributions – Restricted Donations | (Optional) If you want to separate clearly between unrestricted and restricted contributions at the account level. You can also do this purely via `Fund`. |
| 4200 | **Grant Revenue**                    | Cash received from reimbursement / grant programs (e.g. DOL Stand Down).                                                                                   |
| 4300 | **In-Kind Contributions**            | Fair-value of in-kind goods (food, clothing, gear). Used by `record_inkind`.                                                                               |
| 4400 | Event Revenue – Fundraisers          | Ticket sales, registrations from events like the Memorial Ride.                                                                                            |
| 4500 | Merchandise Sales                    | Sales of hats, shirts, etc., if you track those separately from donations.                                                                                 |

MVP: you can get very far with **4100, 4200, 4300** and add 4400/4500 later.

---

### Program Expenses (5000s) – “Doing the mission”

This is where `5200` lives today in your code.

| Code | Name                                 | Purpose / Usage                                                                                                                                                |
| ---- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 5100 | Direct Client Assistance             | Gift cards, bus passes, hotel vouchers, direct support to vets.                                                                                                |
| 5110 | Program Supplies – Stand Down / Kits | Supplies for Welcome Home kits, Stand Down event gear, hygiene kits, etc.                                                                                      |
| 5120 | Food & Hospitality – Programs        | Food for Stand Down, snacks at program events, etc.                                                                                                            |
| 5130 | Transportation – Program             | Fuel, vehicle rental, bus charters related to direct services.                                                                                                 |
| 5200 | **Program Supplies – General**       | This is the generic “program expense” account you’re already using in `log_expense`. You can keep using 5200 as the catch-all until you want more granularity. |
| 5300 | Event Costs – Memorial Ride          | Specific event-type program costs, if you want separate tracking.                                                                                              |

You do **not** have to use all these out of the gate. For simplicity:

- Keep using **5200** for all program expenses in code for now.

- Later, when Governance wants clearer reports, you can start mapping certain categories to more specific codes (5110, 5120, 5130, etc.) based on your `category` field.

---

### Management & General (6000s) – “Keeping the doors open”

| Code | Name                      | Purpose / Usage                    |
| ---- | ------------------------- | ---------------------------------- |
| 6100 | Office Rent & Utilities   | Rent, electricity, phone/internet. |
| 6110 | Office Supplies & Postage | Printer ink, paper, postage, etc.  |
| 6120 | Insurance                 | General liability, D&O, etc.       |
| 6130 | Professional Services     | Accounting, legal, tech support.   |

These would be used when Calendar Projects or Admin tasks log **overhead** expenses rather than program costs.

---

### Fundraising (7000s) – “Raising money”

| Code | Name                            | Purpose / Usage                                                               |
| ---- | ------------------------------- | ----------------------------------------------------------------------------- |
| 7100 | Fundraising Event Costs         | Venue rental, food, printing for fundraising events (Memorial Ride overhead). |
| 7110 | Donor Cultivation & Stewardship | Donor dinners, sponsor thank-you gifts, etc.                                  |

Again, you can start by treating all this as 5200 or 6100 and only break out 7100+ when/if you want that separation.

---

## 3. How this plugs into the existing code

Now you can make your Finance code point to **named accounts**, not “magic numbers in someone’s head”:

- In `services_journal.log_donation`:
  
  - `bank_account_code` default → `"1000"`
  
  - `revenue_account_code` default → `"4100"`

- In `services_journal.log_expense`:
  
  - `expense_account_code` default → `"5200"`
  
  - `bank_account_code` default → `"1000"`

Later:

- For grants:
  
  - Reimbursement revenue lines → `"4200"`.

- For in-kind:
  
  - Use `"4300"` for in-kind revenue and maybe a parallel in-kind expense code if you want full GAAP.

And for Future Dev reading the code:

- They see `"4100"` and the doc says **Contributions – Cash Donations**.

- They see `"5200"` and the doc says **Program Supplies – General**.

- They aren’t guessing.

---

## 4. Where to store / document this in VCDB

To “canonize” it and remove magic:

1. **Doc file**  
   Add something like `docs/finance_chart_of_accounts.md` or include a CoA section in your existing “Project Ethos / Finance” doc. Paste these tables in.

2. **Seed data**  
   Make sure `Account` table seeds match this chart (code + name + type). Then:
   
   - `services_journal` can rely on these codes existing.
   
   - Governance policy files (budget, funding) can reference account types and fund mappings.

3. **Comments in code**  
   In `services_journal.py`, near the defaults:
   
   ```python
   DEFAULT_CASH_ACCOUNT = "1000"  # Operating Cash – Checking
   DEFAULT_CONTRIB_REVENUE_ACCOUNT = "4100"  # Contributions – Cash Donations
   DEFAULT_PROGRAM_EXPENSE_ACCOUNT = "5200"  # Program Supplies – General
   ```
   
   That makes the link very explicit.

---

If you want, next pass we can:

- Turn this into a **ready-to-drop markdown file** for your repo,

- Or sketch the seed data for the `Account` table (list of inserts) so the DB and docs stay in lockstep.
