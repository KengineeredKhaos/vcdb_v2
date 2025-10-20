# VCDB v2 — Project README (Ethos • Canon • Roadmap)

> This README is the **opening statement** for each new dev thread. It captures the non‑negotiables (Ethos), the frozen **Canon** (write‑path ledger, RBAC, core libs), and the current **Roadmap** with milestones and checklists. Keep this file updated as we ship.

---

## Ethos (non‑negotiables)
- **Skinny routes, fat services.** Routes glue inputs to services; all business logic lives in services.
- **Vertical slices own their data** and SQL. No cross‑slice reach‑ins; only call through **Extensions contracts**.
- **ULID everywhere** for opaque IDs (26‑char); all primary keys and foreign keys.
- **Ledger is the single source of truth** for mutations. Append‑only, hash‑linked per `chain_key`, **no PII**.
- **Auth owns RBAC**, Governance owns system policies/taxonomies (not RBAC). RBAC is read via **Auth contract**.
- **Time**: naive UTC in DB; ISO‑8601 `Z` (ms) at the edges; helpers live in `lib/chrono.py`.
- **Templates**: Jinja `StrictUndefined`; CSRF on all POST forms; Option‑B macros.
- **Observability**: structured JSON logs with `request_id`/`actor_id`; nothing is deleted—only archived.
- **Deployment posture**: code/venv read‑only; writable only under `/srv/vcdb/var/{db,log,tmp,cache,uploads,backups}`.

---

## Canon (frozen APIs — do not modify without approval)

### Ledger write‑path (ledger‑core v1.0.0)
- `app/slices/ledger/models.py` — `LedgerEvent` with `id, chain_key, domain, operation, event_type, actor_ulid, target_ulid, request_id, happened_at_utc, created_at_utc, refs_json, changed_json, meta_json, prev_hash_hex, curr_hash_hex` (indexes on chain_key+id, request_id, event_type).
- `app/slices/ledger/services.py` — `_canon_envelope`, `_hash_env`, `append_event(...)`, `verify_chain(chain_key=None) -> dict`.
- `app/extensions/contracts/ledger/v2.py` — `emit(...) -> EmitResult`, `verify(chain_key=None) -> dict`.
- `app/extensions/event_bus.py` — `emit(...)` façade forwarding to `contracts.ledger.v2.emit`.

### RBAC (rbac‑core v1.0.0)
- `app/lib/security.py` — **only public RBAC facade**: `require_login`, `require_roles_any`, `require_roles_all`, `require_permission`, `require_feature`, `current_user_ulid`, `current_user_roles`, predicates (`user_has_any_roles`, `user_has_all_roles`, `user_has_permission`).
- `app/extensions/contracts/auth/v2.py` — **read‑only** Auth contract: `get_user_roles(user_ulid) -> list[str]`, `list_all_role_codes() -> list[str]`.
- Config **PERMISSIONS_MAP** controls permission→role mapping (future‑proof shim until permission contracts exist).

### Lib Core (lib‑core v1.0.0)
- `app/lib/chrono.py` — UTC & ISO helpers (`utcnow_aware`, `utcnow_naive`, `ensure_aware_utc`, `as_naive_utc`, `now_iso8601_ms`, `parse_iso8601`, `to_iso8601`).
- `app/lib/models.py` — `ULIDPK`, `ULIDFK`, `IsoTimestamps` (String(30) ISO zulu timestamps, ms).
- `app/lib/jsonutil.py` — `stable_dumps/loads`, **aliases** `dumps_compact`, `try_parse_json`.
- `app/lib/ids.py` — ULID helpers (`new_ulid`, min/max for windows).
- `app/lib/hashing.py` — SHA‑256 helpers (`sha256_text`, `sha256_json`).
- `app/lib/logging.py` — JSONLine formatter + domain loggers; idempotent setup.
- `app/lib/request_ctx.py` — ContextVars for `request_id`, `actor_id`, helpers to ensure/fetch.
- `app/lib/utils.py` — normalize/validate: email, phone (NANP), EIN (+ `assert_valid_*`).
- `app/lib/schema.py` — jsonschema validate helpers, enums, `try_validate_json`.
- `app/lib/pagination.py` — `Page[T]` + `paginate_list/sa/auto`.

Each canon file begins with the banner:
```
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# Purpose: <short purpose>
# Canon API: <name> v1.0.0 (frozen)
```

---

## Directory Layout (v2)
```
app/
  extensions/            # contracts + adapters (versioned)
  lib/                   # canon libraries (frozen)
  services/              # shared cross‑cutting services (non‑DB)
  slices/
    auth/
    governance/
    ledger/              # write path canon lives here
    customers/
    resources/
    sponsors/
    finance/
    admin/
    logistics/
    calendar/
  static/
  templates/
    layout/
archive/
exports/
instance/
logs/
scaffolding_docs/
scripts/
tests/
```

---

## Slice Guardrails (flexible, versioned)
These guardrails prevent accidental coupling while staying flexible via **versioned contracts**, **feature flags**, and **migration notes**. Each slice gets a clear remit; anything beyond that requires a new contract or a version bump.

### General rules for all slices
- **Own your data** (tables + SQL). No direct reads/writes to other slices.
- **Expose only via `extensions/contracts/*_vN.py`** (pure functions, DTOs, explicit errors). No returning ORM models.
- **Emit one ledger event per mutation** through the **canon event bus**.
- **PII boundary:** **Only the Entity slice may store PII.** No full SSN anywhere (ever). Entity may store personal names, contact info (email/phone), postal addresses, and **SSN last‑4 only**. EINs belong under EntityOrg. All other slices must store **anonymized facts keyed by `entity.ulid`** and never copy PII.
- **No PII in ledger/logs** (ULIDs + compact summaries only).
- **Archive, don’t delete**; add `archived_at` and provide `archive_*()` services.
- **Auth for RBAC only**; Governance for policies/taxonomy only.

### Auth (RBAC owner)
- **Can:** sessions, password mgmt, user↔role assignments, list role codes.
- **Cannot:** set system policies, write to other slice tables.
- **Contracts:** `auth_v2.get_user_roles`, `list_all_role_codes` (read-only).
- **Emits:** `auth.user.created/updated/role.attached/role.removed`.
- **Future flexibility:** add `permissions_v2` later without changing route decorators (permission shim already in `lib/security`).

### Governance (policy/taxonomy)
- **Can:** versioned policies (states, taxonomies, caps), validation helpers.
- **Cannot:** assign RBAC roles; write into other slices.
- **Contracts:** `governance_v2.get_authorized_system_roles`, `validate_*`.
- **Emits:** `governance.policy.created/updated`.
- **Flex:** evolve schemas via policy versioning; consumers read latest via contract.

### Ledger (audit write-path — canon)
- **Can:** append/verify events; provide read pagination under a **separate read contract**.
- **Cannot:** business decisions; store PII.
- **Contracts:** `ledger_v2.emit`, `verify`. (Reader to be added as `ledger_read_v1`.)
- **Emits:** none (it is the sink).
- **Flex:** add new chains via `chain_key` without schema change.

### Entity (system identity & sole PII store)
- **Can:** create/get/archive entity; attach/remove **system roles** (customer/resource/sponsor/governor); **store and update PII** (personal names, emails, phones, postal addresses) and **SSN last‑4 only**; store **EIN** for org entities. Provides normalized/validated contact fields using `lib/utils`.
- **Cannot:** expose PII directly to other slices except via **Entity contracts** designed for PII access, and only where required; ledger/logs must not include PII.
- **Contracts:** `entity_v2.ensure_person/org`, `add/remove_entity_role`, plus **PII‑scoped getters** (to be designed) with strict RBAC.
- **Emits:** `entity.created/archived`, `entity.role.attached/removed`, and PII‑update events that carry **no PII** (field names only) in `changed`.
- **Flex:** additional PII fields live here exclusively; other slices must reference `entity.ulid`.

### Resources
- **Can:** register orgs/services; capability matrix; readiness status.
- **Cannot:** account/finance; allocate funds.
- **Contracts:** `resources_v2.register`, `classify`, `list`.
- **Emits:** `resource.created/updated/classified`.
- **Flex:** capacity/SLA later; keep through contracts.

### Customers
- **Can:** store **needs assessments** and qualifying factors (e.g., homelessness, disability flags), veteran status, branch & discharge characterization, era of service, age/locale demographics — **all anonymized and keyed to `entity.ulid`** (no duplicated PII).
- **Cannot:** store names, emails, phones, addresses, or any direct PII; no SSN data of any kind.
- **Contracts:** `customers_v1.register_assessment`, `update_assessment`, `list_by_filters` (returns anonymized DTOs), `get_customer_summary(entity_ulid)` (PII‑free aggregates).
- **Emits:** `customer.created/updated` with field‑name deltas only.
- **Flex:** expand assessment schema via versioned policies; raw sensitive notes should live in an encrypted notes vault later, still keyed by `entity.ulid`.

### Sponsors
- **Can:** record donations (monetary/in‑kind), allocations.
- **Cannot:** general ledger; issue payments.
- **Contracts:** `sponsors_v1.record_donation`, `make_allocation`.
- **Emits:** `sponsor.donation_recorded`, `sponsor.allocation_made`.
- **Flex:** add reimbursement flows later.

### Logistics (replaces Inventory)
- **Can:** manage assets (fixed/high‑value), consumables, stock levels, sourcing, per‑item funding source, assignment to entities; coordinate kit builds with Calendar.
- **Cannot:** approve spending authority; hold accounting books.
- **Contracts:** `logistics_v1.register_asset`, `assign_asset`, `reserve_stock`, `list_inventory`.
- **Emits:** `logistics.asset.added/assigned/returned`, `inventory.stock.reserved/issued/reordered`.
- **Flex:** add scanners or batch ops via new contract versions.

### Finance
- **Can:** record spending authority, reconcile monetary & in‑kind flows, grant fund tracking, cross‑slice reporting.
- **Cannot:** mutate other slice data directly.
- **Contracts:** `finance_v1.record_expense`, `record_in_kind`, `reconcile`, `report`.
- **Emits:** `finance.expense.logged`, `finance.reconciliation.completed`.
- **Flex:** swap accounting backend by adapter without changing contracts.

### Admin
- **Can:** manage RBAC assignments (via Auth contract), entity domain roles (via Entity contract), assign `governor`, update Governance policies, officer/pro‑tem lifespans, user spending authorities.
- **Cannot:** bypass slice boundaries; writes always go through owning contracts.
- **Contracts:** Admin exposes **no contracts**; it **calls** other slices’ contracts.
- **Emits:** mirrors underlying slice events (Admin is orchestration only).

### Calendar
- **Can:** full scheduling **and** special‑events project management: projects, tasks/subtasks, assignments, status flags, and funds/spending‑authority tracking; coordinates with **Finance** (budgets/spend) and **Logistics** (assets/kits).
- **Cannot:** become the system of record for Finance or Logistics data (only references and summaries; owners remain those slices).
- **Contracts:** `calendar_v1.create_project`, `add_task`, `assign_actor`, `set_status`, `link_finance_ref`, `link_logistics_ref`, `list_by_ref` (exact names to be finalized during build).
- **Emits:** `calendar.project.created/updated/archived`, `calendar.task.created/updated/assigned/status_changed`, `calendar.note.added/updated/cancelled`.
- **Flex:** introduce resource booking/Gantt and critical‑path later via `calendar_v2` without breaking v1.

### Web (public)
- **Can:** render public pages; read-only via contracts.
- **Cannot:** mutate domain data.
- **Contracts:** none (calls read contracts only).

### Extensions (contracts hub)
- **Rule:** versioned, pure, typed DTOs; no ORM; raise contract-specific errors.
- **Flex:** introduce `*_v3` alongside v1/v2; never break old until migrated.

### Flexibility mechanics we rely on
- **Versioned contracts:** Add `*_vN+1` next to existing; migrate callers gradually.
- **Feature flags:** Gate unfinished features/routes (`@require_feature("FLAG")`).
- **Data migrations:** forward migrations only; archival over deletion; backfill jobs live under `scripts/`.
- **Deprecation policy:** mark old contracts with a deprecation window; remove only after callers migrate.

---

## Build Order & Scope (v2)
1) **Auth** — sessions + minimal RBAC (done; canon locked).
2) **Governance** — policy registry, US state choices, taxonomy, spending caps; **admin UI for policies**.
3) **Ledger** — append + verify (done; canon locked).
4) **Entity** — create/get/archive + role attach/remove via contracts; emits `entity.*`.
5) **Resources** — minimal register/list; capability matrix validation via Governance; emits `resource.*`.
6) **Customers** — minimal register/list (no PII beyond allowed basics); emits `customer.*`.
7) **Sponsors** — donation recorded; emits `sponsor.*`.
8) **Logistics** — manages fixed/high-value assets and assignments to entities; durable goods & consumable inventory; stock levels, ordering/sourcing, per-item funding source tracking (grants/donor restrictions); coordinates with Calendar for project kit building; may expand over time.
9) **Finance** — central accounting suite; spans Resources, Sponsors, Calendar, Logistics, etc.; tracks spending authority, monetary & in-kind donations, grant funds and restrictions; reconciliation/reporting.
10) **Admin** — administrative controls: edit RBAC roles and user assignments; edit entity domain roles post-creation; assign `governor` role; update Governance policies; manage officer / pro‑tempore / governor lifespans; assign spending authorities.
11) **Calendar.SpecialEvents** — simple notes with ULID refs; emits `calendar.note.added`.
12) **Web** (public) — simple home + docs library.

## Development Workflow (how we ship without churn)
- **Models first**: define slice‑owned tables & fields; pick formats (ULID FKs, ISO timestamps, JSON columns where appropriate); add `archived_at`.
- **Services second**: implement manipulations/business rules; no cross‑slice imports.
- **Contracts third**: expose read/write via `extensions/contracts/*_vN.py` (DTOs, explicit errors, dry_run→commit for mutations). **Canonize at the contract**.
- **Routes fourth**: skinny orchestration only; apply RBAC/permission/feature guards explicitly.
- **Templates fifth**: Jinja StrictUndefined; CSRF on POST; Option‑B macros; minimal logic.
- **Styling last**: CSS aesthetics and ergonomics once flows are stable.

---

## Milestones & Checkpoints

### M0 — Core frozen (✅ this doc)
- Ledger write path canon (models/services/contract/bus) **locked**.
- RBAC facade + read‑only Auth contract **locked**.
- Lib Core canon **locked** with `__all__` and banners.

### M1 — Governance Admin UI (in progress)
- Policy list/edit routes (CSRF) with emits `governance.policy.{created|updated}`.
- Seed baseline policies: role codes (Auth), taxonomy, state choices, spending caps.
- **Checkpoint:** `flask ledger-verify --chain governance` OK after edits.

### M2 — Entity Stable
- Contract `entity_v2` (ensure_person/org, role attach/remove) using dry_run→commit pattern.
- Emits `entity.*` events; archive only (never delete).
- **Checkpoint:** Contract tests pass; ledger verify OK.

### M3 — Thin Vertical (Resource + Customer)
- Minimal register/list flows through contracts; Governance validation; ledger emits.
- **Checkpoint:** end‑to‑end manual walk: create Entity → attach role → register Resource and Customer → verify ledger.

### M4 — Read Views & Audit
- Simple ledger reader (separate **read** contract) to filter by `chain_key`, `request_id`.
- Admin audit page: paginate events, link to entities/policies.
- **Checkpoint:** Smoke tests on `ledger:read` permission.

---

## Definition of Done (per feature)
- All cross‑slice calls use **contracts** — no direct imports.
- Every mutation: **dry_run → commit** and emits a single **Ledger** event.
- JSON logs include `request_id` and service operation.
- No PII in ledger/logs; only ULIDs, event types, compact JSON.
- Jinja `StrictUndefined`; **CSRF** on all forms.
- Feature flagged until tests pass; boot checks quiet unless enabled.

---

## Testing Strategy
- **Contract tests** (DTO shapes, error models) before service/route tests.
- **Ledger canaries**: golden tests verify function signatures of canon; `ledger-verify` runs in CI.
- Keep UI tests minimal; assert presence of CSRF fields and 200/302 outcomes.

---

## Operational Notes
- **Prod layout**: code under `/srv/vcdb/app` (read‑only), venv `/opt/vcdb/venv` (read‑only); writable `/srv/vcdb/var/*`.
- **Backups**: `/srv/vcdb/var/db` and `/srv/vcdb/var/backups`.
- **Web server**: Apache/mod_wsgi daemon mode; set `XDG_CACHE_HOME` & `TMPDIR` to var paths.

---

## Change Governance (how canon can change)
- Propose change → bump **Canon API version** header → migration plan (if schema) → update golden tests → cut release note.
- No silent edits to canon files. Banners remain.

---

## Quick Commands
```bash
# DB migrations
flask db migrate -m "message" && flask db upgrade

# Verify ledger chains
flask ledger-verify                # all chains
flask ledger-verify --chain governance

# Run tests (quiet)
pytest -q
```

---

## Open TODOs / Next Up
- [ ] Finalize Governance seed set (roles/taxonomy/states/spending caps).
- [ ] Entity contract v2: dry_run and commit flows.
- [ ] Resource+Customer thin vertical via contracts.
- [ ] Ledger read contract + admin audit view.

> **Reminder:** Keep this README updated when we cross a milestone or freeze a new canon.

