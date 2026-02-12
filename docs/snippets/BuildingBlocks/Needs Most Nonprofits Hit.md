# Needs Most Nonprofits Hit

# Funding & gifts

- **Pledges & installments**: track pledged vs. received; ledger ops for `pledge.created/adjusted/written_off/paid`.

- **Recurring donations & expirations**: renewal cadence, failed/retired payments; retry policy.

- **Matching gifts / soft credits**: attribute impact to both employee (soft) and employer (hard).

- **Restricted vs. unrestricted funds**: enforce “spend from bucket X only”; grant/fund balance projections.

- **In-kind valuation**: capture fair-market value for goods/services; show both quantity & valuation in reports.

# Grants & compliance

- **Allowable cost categories**: budget lines tied to a grant; validation at the point of spend.

- **Period of performance**: block/flag ledger ops outside grant window.

- **Documentation linking**: receipts, timesheets, approvals; store hashes/URIs in `refs_json`.

- **Single audit/Uniform Guidance hooks** (if applicable): exportable audit packages by grant.

# Constituents & identity

- **Householding**: link people at the same address for mailings/soft credit.

- **Dedup & merge**: canonicalize entities; keep ULID lineage (superseded_by).

- **Consent & communications prefs**: per-channel opt-in/out with timestamps and source.

# Programs & service delivery

- **Eligibility checks**: policy-driven rules (income, residency); record decisions and reasons.

- **Waitlists**: priority queues; FIFO with overrides (logged to ledger).

- **Attendance / service encounters**: per-event or per-visit records tied to outcomes.

# Volunteers & staffing

- **Shift scheduling**: assignments, check-in/out; hours to ledger for valuation and reporting.

- **Background checks & expirations**: status, vendor ref, next refresh date.

- **Expense reimbursements**: mileage/per diem flows distinct from procurement.

# Events & campaigns

- **Ticketing / RSVP**: counts, no-shows, comps; simple seating tiers if you need them later.

- **Campaign attribution**: UTM/referrer capture; soft credit to ambassadors/peer-to-peer.

# Finance & accounting alignment

- **Chart of accounts mapping**: optional dimension on ledger ops for QB/ERP sync.

- **Close periods**: lock prior months; only allow adjustments via explicit correction ops.

- **Reconciliation jobs**: compare ledger projections to bank/QB snapshots; surface variances.

# Data governance & privacy

- **PII redaction profiles**: contract-level field suppression by role.

- **Records retention schedules** (you already pinned the Ethos): automate `archive_at` dates per class of record.

- **Incident logging**: record privacy/security incidents with containment steps.

# Reporting & analytics

- **Outcome/KPI model**: define a minimal set now (served, retained, graduation, cost per outcome).

- **Saved report definitions**: parameterized, versioned, owned by user/team; exportable to CSV.

- **Freshness banners**: every report shows projection watermark (you already planned this—keep it visible).

# Integrations & ops

- **Import pipelines**: CSV mappers with column validation & idempotency (use correlation_id).

- **Webhooks / outbound events**: optional; throttle & retry (ledger emits, but a dispatcher helps).

- **Background jobs**: APScheduler/Celery minimal wrapper; job events to ledger.

- **Backups & restores**: snapshot + hash; restore emits a `system.restore.completed` event.

# Internationalization & access

- **Locale/time-zone policy**: store UTC Z; render in user TZ; governance policy for allowed locales.

- **Accessibility**: WCAG checklists for templates; error summaries; keyboard navigation.

# DX & safety rails

- **Feature flags**: flip on projections or new contracts by slice.

- **Maintenance mode**: serve read-only with banner; only allow privileged writes.

- **Test fixtures**: golden seed covering donations, in-kind, a grant, inventory, a case.

---

## What to bake **now** (lightweight, high leverage)

1. **Ledger domains/ops catalog**: add entries for pledges, soft credit, restricted funds, in-kind, reimbursements, waitlist, background check, attendance. (Even if UI waits.)

2. **Projection scaffolds**: `fund_balance`, `grant_spend`, `inventory_on_hand`, `volunteer_hours`, each with `schema_version`, `last_event_ulid`, `rebuilt_at`.

3. **Contracts**:
   
   - `ledger_v1.list_events` (you have)
   
   - `grants_v1.fund_balances(filters)`
   
   - `inventory_v1.snapshot(as_of)`
   
   - `volunteers_v1.hours(range)`  
     Start with read-only; add write DTOs later.

4. **Governance policies**: allowable categories per grant, retention schedules, consent defaults, locale/TZ allowlist.

5. **Entity hygiene**: householding fields (household_ulid), `superseded_by` for merges, basic dedup utilities.

This keeps you aligned with your Ethos (skinny routes, fat services, slice-owned data, extensions as the only bridge) and avoids future “patch & stitch.”
