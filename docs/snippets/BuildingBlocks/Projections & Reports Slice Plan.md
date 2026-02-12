# Projections & Reports Slice Plan

This is a perfect fit for **Option 2 (Projections & Reports)** plus a tiny, append-only **“Cases” workbench** for curated bundles of ledger events.

Here’s a tight plan that keeps slices skinny, uses the Ledger as source-of-truth, and gives you the UX you want.

## What to build

### A) Reports slice (read models only)

Purpose: fast reads for non-technical users. Built **from** ledger events; never writes domain state.

#### Projections (materialized read tables)

- **inventory_snapshot** (current stock by item)
  
  - Built by folding all `inventory.*` events (received, adjusted, issued, returned).
  
  - Columns: `sku`, `on_hand`, `allocated`, `as_of_ts`, plus convenience dims (category, location).

- **inventory_issue_history** (customer-facing view)
  
  - Flattened rows per issue/return event with joins to DTOs for display names (via contracts).
  
  - Columns: `event_ulid`, `happened_at`, `customer_ulid`, `sku`, `qty`, `issued_by_ulid`, `case_ulid?`.

- **grant_spend_summary**
  
  - Rollup of `funding.*` and related `inventory.issue`/`expense.booked` events, keyed by `grant_ulid` (or `program_ulid`).
  
  - Columns: `grant_ulid`, `period`, `amount_committed`, `amount_spent`, `remaining`, `as_of_ts`.

- **calendar_rollup**
  
  - Derived from Calendar events + correlated ledger events using `correlation_id`.

> Mechanics: one idempotent job per projection (cron or on-demand) that scans from the last processed `ledger.id`, applies events, and persists a watermark. If desired, allow full rebuild.

#### User flows powered by these projections

1. **Printable inventory list**  
   Route: `/reports/inventory/list?location=…&category=…` → render from `inventory_snapshot` with optional CSV/PDF export.

2. **Customer issue history**  
   Route: `/reports/customers/<entity_ulid>/history` → read `inventory_issue_history` filtered by `customer_ulid`.

3. **Grant “spend to date”**  
   Route: `/reports/grants/<grant_ulid>` → pull `grant_spend_summary` rows + related case bundles (see Cases below).

4. **Calendar project status**  
   Route: `/reports/calendar/<project_ulid>` → show `calendar_rollup` + linked events by `correlation_id`.

---

### B) Cases slice (append-only “holding pen”)

Purpose: let staff **curate** a set of ledger events into a named bundle (a “case”), add metadata, and freeze/archive it at closure.

#### Minimal data model (append-only)

- `case`
  
  - `case_ulid (PK)`, `title`, `kind` (`grant`, `audit`, `project`…), `created_at`, `created_by_ulid`, `status` (`open|closed|archived`), `notes_json` (small), `tags` (comma or tiny JSON).

- `case_event_link` (append-only)
  
  - `case_ulid (FK)`, `event_ulid`, `added_at`, `added_by_ulid`.

- (Optional) `case_refs`
  
  - `case_ulid`, `ref_kind` (`grant_ulid`, `customer_ulid`, `project_ulid`…), `ref_value`.

**Rules**

- Never delete rows; closing a case writes a `status = closed` and a **ledger event** `case.closed`.

- Archiving writes `case.archived` and optionally dumps a point-in-time JSON export.

**How it’s used**

- Staff creates case “Grant ABC FFY2026”.

- They search ledger (by domain/operation/period/correlation_id) and **add events** to the case (just storing event ULIDs).

- The case view shows: curated list, computed totals (by re-reading those events), and links to Reports slice summaries.

- At close, one click → freeze + export (JSON/CSV bundle), emit ledger `grant.case.closed` with `refs_json` including `case_ulid`.

---

## Event contracts you’ll lean on

- `ledger.search(query)` contract already supports: `domain`, `operation`, `time range`, `entity_ulid`, `correlation_id`, paging.

- Add small helpers in the Ledger contract for common patterns:
  
  - `list_inventory_events(sku|location|since_event_ulid)`
  
  - `list_customer_issues(customer_ulid, date_from, date_to)`
  
  - `list_grant_related(grant_ulid, date_from, date_to)` (by `refs_json` or `correlation_id` conventions)

> Keep them **read-only**, returning DTOs with: `event_ulid`, `happened_at`, `domain`, `operation`, `actor_ulid`, `target_ulid`, `changed_fields`, `refs`, `correlation_id`.

---

## Indices you’ll want (Ledger)

- `(domain, operation, happened_at)`

- `(actor_id)` and `(target_id)`

- `(correlation_id)`

- GIN/JSON index equivalents on `refs_json` (SQLite: consider virtual table or companion scalar columns for frequent keys).

- `(event_ulid)` obviously PK/unique.

---

## How the four use-cases map

1. **Physical inventory list**
   
   - Build from `inventory_snapshot` projection.
   
   - Filterable by location/category; output CSV/PDF.
   
   - Optional “include open allocations” toggle.

2. **History for a customer**
   
   - Either query `inventory_issue_history` directly, or for live accuracy read ledger `inventory.issue|return` filtered by `target_id = customer_ulid` and enrich with SKU names via Resources contract.

3. **Grant holding pen + spend report**
   
   - Create a **Case(kind='grant')** for each grant.
   
   - Staff add related events (pledges, disbursements, issues, expenses) by searching ledger; links are append-only.
   
   - The Case page shows:
     
     - curated event list,
     
     - computed **point-in-time spend** (sum over linked events),
     
     - live “spend to date” chart (from `grant_spend_summary` projection).
   
   - On close → export and emit `grant.case.closed`.

4. **Calendar event/project status**
   
   - Calendar emits events with a shared `correlation_id` per project.
   
   - Reports slice queries ledger by `correlation_id` to assemble a timeline; Cases can link those event ULIDs if staff wants curated context.

---

## Folder shape (concise)

```
app/
  slices/
    reports/
      __init__.py
      routes.py          # report UIs & CSV/PDF
      services.py        # read-only projection queries
      models.py          # projection tables (SQLAlchemy)
      jobs.py            # rebuild/advance projections
    cases/
      __init__.py
      routes.py          # create, add events, close, export
      services.py        # append-only logic
      models.py          # Case, CaseEventLink
  extensions/
    contracts/
      ledger/v1.py       # search helpers
      resources/v1.py    # SKU lookup for enrichment
      customers/v1.py    # name display, etc.
```

---

## A few concrete design tips

- **Projection rebuild:** store a watermark (`last_event_ulid` or offset). Jobs read new events, apply, commit watermark. Provide a full rebuild CLI for safety.

- **Case totals:** don’t store running totals—compute from linked event payloads (or read from projections) to avoid divergence.

- **DTO timestamps:** always **UTC ISO-8601 Z** over the wire; convert to local in templates as needed.

- **Exports:** make every report page have an `/export.csv` twin. CSV first; PDF later if you want.

- **Security:** Cases are admin/staff-only; Reports have per-role views (auditor can read projections; only staff can export PII-adjacent joins).

---
