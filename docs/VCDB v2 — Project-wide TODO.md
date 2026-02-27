# VCDB v2 — Project-wide TODO

Conventions:

- Status: [ ] todo, [~] in-progress, [x] done
- Use **@TODO:** as the queue marker for new work.
- Keep items atomic (one outcome per TODO), but allow sub-bullets.
- Prefer links to files/paths and named functions when applicable.

---

## Now

### Foundation docs and guardrails

- [ ] @TODO: Add a pagination smoke test (regression tripwire).
  
  - exercise `app/lib/pagination.py::paginate()` in app context
  - run against a trivial `select()` (SQLite) to catch extension wiring drift

- [ ] @TODO: Generate a “strip map” of the Entity Wizard flow.
  
  - essential form data acquisition per step (what/why)
  - nonce lifecycle: issue → expect → consume (stale-submit behavior)
  - route responsibilities (PRG, redirect targets, commit/rollback)
  - service responsibilities (normalize/validate, DB reads/writes)
  - no-op rules (no write/no flush/no ledger)
  - `db.flush()` boundaries vs `db.commit()` boundaries
  - ledger entry assembly (field names only, request_id/actor/target/op)
  - confirmation UX (created/updated views) and resume behavior
  - include a sequence diagram + per-step checklist

### Customers: contracts first

- [ ] @TODO: Clean up `customers_v2` contract (keep it small and stable).
  - remove DTOs camped inside the contract (DTOs live in slice mapper)
  - keep contracts minimal:
    - read cues (non-PII)
    - controlled history append write
  - standardize ContractError wrapping + error codes

### Governance: policy-driven taxonomy + reassessment

- [ ] @TODO: Governance policy for Customers slice enumerations + needs taxonomy.
  
  - move constants out of `customers/services.py` into Governance JSON
    (read-only via governance_v2 contract):
    - veteran_statuses, homeless_statuses, veteran_methods
    - branches, eras
    - need_category_keys
    - tier groupings (tier1/tier2/tier3 key lists)
    - rating_allowed + rank map (immediate/marginal/sufficient ordering)
  - proposed policy file:
    - `app/slices/governance/data/policy_customer_taxonomy.json`
  - add schema + validation:
    - `app/slices/governance/data/schemas/policy_customer_taxonomy.schema.json`
    - semantic checks:
      - keys unique
      - tier groupings cover all categories
      - rank entries only for 1..3-rated values
      - allowed includes unknown/na
  - expose via contract:
    - `governance_v2.get_customer_taxonomy() -> CustomerTaxonomyDTO`
    - cache in services (TTL) so Customers doesn’t repeatedly hit loader
  - Customers consumes taxonomy:
    - validate inputs + compute rollups from policy
    - remove hard-coded `_VETERAN_STATUS`, `_TIER1`, `_RANK`, etc.
  - exception note:
    - keep state codes in `app/lib/geo.py` as the single exception (canon)

- [ ] @TODO: Governance policy for time-based Customer needs reassessment.
  
  - define policy intent:
    - reassessment interval(s) (e.g., default_days, tier1_immediate_days)
    - optional triggers (watchlist=true, homeless_status=verified, etc.)
    - what constitutes “overdue” (CustomerProfile.last_assessed_at_iso)
  - decide where the system surfaces the trigger:
    - CustomerDashboard shows “Reassess due” banner (staff-visible)
    - optional silent admin_tags for systemic review (Admin sweep)
  - implement mechanics (later, after policy exists):
    - service computes `is_reassess_due` (read-only) from governance rules
    - UI shows banner + provides “Begin reassessment” action
    - reassess start snapshots current version → CustomerHistory blob
      (kind="needs_reassessment") then calls `needs_begin()`
  - ensure no spam:
    - snapshot only on reassessment start (not on every needs_set_block())

### Admin: silent-review signals (separate from Customers staff UI)

- [ ] @TODO: Implement Admin sweep job for CustomerHistory admin tags.
  
  - CustomerHistory stores `has_admin_tags` + `admin_tags_csv`
  - Admin job scans new history rows (cursor-based, idempotent)
  - create admin-only alerts/tasks (no PII; ULIDs + reason codes only)
  - avoid duplicates via unique key (history_ulid + reason_code)

- [ ] @TODO: Define minimal Admin alert storage & UI (v1).
  
  - table: `admin_alert` (target_entity_ulid, reason_code, happened_at, status)
  - view: “Review Queue” list; link to entity + history entry
  - optional: bridge into Calendar tasks later

- [ ] @TODO: Clarify inbox evolution path (avoid dual systems).
  
  - Dataset #7 “Admin Inbox” is v0 (directly reads CustomerHistory flags)
  - v1: Admin Inbox becomes a view over `admin_alert` (produced by sweep)

---

## Later

### Standard guard helpers (alignment sweep)

- [ ] @TODO: Sweep mutating services for standard guard helpers.
  - add `_ensure_actor_ulid()` alongside `_ensure_entity_ulid()` and
    `_ensure_request_id()`
  - for every mutating service command:
    - call all three guards at the top (fail fast)
    - require `request_id` and `actor_ulid` as keyword-only params
  - apply forward-first; defer refactors of stable/working slices
  - later: deliberate alignment sweep across older slices (Entity, etc.)

---

### Future Dev Documentation

- [ ] @TODO: Document Dev Portal (dev/test landing) utility in Future Dev Toolkit:

- Purpose: safe “cold-call GET” sitemap + smoke-test hub; not workflow-driving.

- Where: web.index renders layout/index_dev.html in dev/test only.

- Features:
  
  - auto सूची of param-free GET routes from current_app.url_map
  - “Known-good entry points” buttons gated by has_endpoint()
  - Probe-all (server-side test_client GET) with status codes + redirects
  - Explicit exclusions: skip admin blueprint; skip auth.dev_* (or mark SKIP)
  - Status legend: ✅ 2xx, ↪ 3xx, ❌ 4xx/5xx, SKIP

- Guardrails:
  
  - Dev/test only; never enabled in prod
  - Probe must not call routes with side effects; keep exclude lists updated

---

## Done (locked / canonized)

### Customers slice canonization

- [x] @TODO: Replace Customers slice schema with the new facet-key design.
  
  - `customer_customer` (card: intake_step/needs_state/tier mins/watchlist)
  - `customer_eligibility` (PK=FK; veteran/homeless + branch/era + method)
  - `customer_profile` (PK=FK; assessment_version + last_assessed metadata)
  - `customer_profile_rating` (12 rows per assessment_version; default `na`)
  - `customer_history` (append-only; envelope-cached columns + data_json)
  - confirm constraints/enums match canon values (branch/era/method/rating scale)
  - dev DB: prefer dump/rebuild (no migration rabbit hole)

- [x] @TODO: Canonize the CustomerHistory “envelope + payload” blob.
  
  - store schema at:
    - `app/slices/customers/data/schemas/customer_history_blob.schema.json`
  - implement Customers-side validation for envelope (payload opaque)
  - cache envelope fields into `customer_history` columns:
    - `schema_name`, `schema_version`, `title`, `summary`, `severity`
    - `public_tags_csv`, `has_admin_tags`, `admin_tags_csv`
    - `source_slice`, `source_ref_ulid`, `happened_at`
  - keep rule: staff UI never renders `admin_tags` (silent review signals)

- [x] @TODO: Implement CustomerHistory append entry path (cross-slice write).
  
  - add `customers_v2.append_history_entry(...)` contract (controlled write)
  - Customers service parses JSON blob, validates envelope, columnizes cache
  - store full blob in `data_json` unchanged (or stable-dumped if dict input)
  - idempotency strategy (optional): allow caller-provided `dedupe_key`

- [x] @TODO: Add producer-side envelope builder helpers (template) and pin usage.
  
  - ensure `history_blob.py` exists in Logistics + Resources
  - docstring: builder must keep in sync with Customers envelope schema
  - add a minimal “usage recipe” snippet in each slice for future devs

- [x] @TODO: Rebuild Customers `services.py` around the new models.
  
  - keep sections: facet ensure / eligibility commands / needs commands / history
  - services are commands and return DTOs (no request/redirect/ledger)
  - implement no-op detection: no write/no flush/no ledger trigger
  - routes own PRG + nonce + commit/rollback + ledger emits

- [x] @TODO: Rebuild Customers `mapper.py` DTOs for the new schema.
  
  - define Row projections vs View DTOs (Row = DB→service, View = outward-facing)
  - provide minimal “quick peek” summary DTO (non-PII)
  - include `EnvelopeDTO` + `ParsedHistoryBlobDTO`

- [x] @TODO: Rewrite Customers routes to support the intake wizard canon.
  
  - PRG + stale-submit defense with `wiz_nonce`
  - deterministic `wizard_next_step(entity_ulid)` resume logic from DB state
  - steps (lean v1): ensure facet → eligibility → needs tier1/2/3 → review → done
  - POST: validate nonce first; stale = flash + redirect; never mutate on stale
  - commit only in routes; services flush only when needed
  - ledger emits only when created or `changed_fields` non-empty

- [x] @TODO: Customer Needs Assessment rules (v1) pinned and implemented.
  
  - precreate 12 rating rows as `na` when needs_state flips to `in_progress`
  - `unknown` reserved for “assessed but unknown/declined”
  - tier rollup rule: min(1/2/3) ignoring `unknown/na`, else tier=`unknown`
  - watchlist remains manual escape hatch; compute “effective cues” in DTOs
  - reassessment: archive prior version snapshot JSON into `customer_history`
    (kind=`needs_reassessment`, schema_name=`customers.needs_snapshot`)
