# Finance Kick Start

## DRMO policy (codified)

- **No calls to `finance.inkind.record.v2`** for DRMO “no fair value” items.

- Track those in **Logistics Inventory** (next slice) as **quantities**; optionally mirror monthly totals via **`finance.stat.record.v2`** (non-monetary).

- If a subset has **reliable valuation** (per Governance), use `inkind.record` with a `valuation_basis` token and attach evidence via Attachments (outside Finance).

---

## Quick start checklist

1. Add the **finance** blueprint to your app.

2. Run your `db_create_all.py --env dev --mode create`.

3. Seed reference data (one time):
   
   - Accounts: `1000 Cash (asset)`, `3000 NA-Without (net_assets)`, `3100 NA-With (net_assets)`, `4100 Contributions-Cash (revenue)`, `4200 Contributions-In-Kind (revenue)`, `5200 Program-In-Kind Expense (expense)`
   
   - Funds: `unrestricted (unrestricted)`, plus any temp/perm codes you use.

4. Hook Sponsors/Resources to call **`finance.journal.post.v2`** for cash receipts; **do not** post DRMO non-monetary.


