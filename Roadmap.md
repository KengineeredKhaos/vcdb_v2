# VCDB v2 — Roadmap to Coherent MVP (Ethos‑Aligned)

> Ethos: skinny routes • fat services • slices own data • cross‑slice only via **Extensions contracts** • ULID everywhere • naive UTC via `lib/chrono.py` • StrictUndefined Jinja • nothing deleted, only archived • Governance owns **system roles/policies**, Auth owns **RBAC**.

---

## North Star (what “coherent MVP” means)

A runnable, self‑consistent vertical slice proving the architecture end‑to‑end:

* Log in (Auth) → create minimal **Entity** → assign a **system role** via Governance contract → emit **Ledger** events → view basic **Resource** catalog and create a minimal **Customer** record linked to the Entity → schedule a placeholder **Calendar** note → JSON logs are structured; every mutation emits a Ledger event with `request_id`.

**Exit criteria for MVP**

* All cross‑slice interactions go through Extensions v2 contracts.
* DB schema uses `ULIDPK`, `ULIDFK`, `IsoTimestamp` helpers only; timestamps from `lib/chrono` only.
* Events stored in **Ledger** (no PII, ULIDs only) with verify script passing.
* Jinja StrictUndefined across templates; CSRF present on POST forms.
* JSON logging operational (domain loggers) with `request_id` propagation.

---

## Workstream 0 — Stabilize Foundations (stop the churn)

**Goal:** Freeze the primitives, park unfinished slices behind flags, and wire observability.

1. **Freeze primitives (library):**

   * `lib/ids` (ULID) ✅
   * `lib/chrono` (UTC helpers) ✅
   * `lib/models` (`ULIDPK`, `ULIDFK`, `IsoTimestamp`) ✅
   * `lib/utils` (phone/email/EIN normalize/validate) — finalize API signatures + tests.
   * `lib/jsonutil` — implement public helpers: `is_jsonable()`, `try_parse_json()`, `dumps_compact()`, `dumps_pretty()`, `scrub_for_log()`.
   * `lib/logging` — ensure `JSONLineFormatter` + domain loggers; add `request_id` MDC style context helper.

2. **Extensions scaffolding:**

   * Contracts folder shape: `extensions/contracts/{governance_v2, auth_v2, entity_v2, ledger_v2, resources_v2}.py`.
   * Contract DTOs + error types; mutation pattern: `dry_run` → `commit` (emits single Ledger event).

3. **Event bus (emit) hardening:**

   * Single publisher facade in `extensions/emit.py` → calls Ledger service; forbid direct slice‑to‑slice writes.

4. **Feature flags:**

   * Disable half‑built slices by default (env var or `config.FeatureFlags`).

5. **Observability & tests:**

   * Request/Correlation ID middleware; log every request start/end.
   * Minimal `pytest` fixtures for `request_id` and ULID generation; remove or xfail flaky tests.

**Definition of Done (W0):** primitives frozen, contracts skeletons compile, emit bus integrated, logging visible in dev runs, flaky tests quarantined.

---

## Phase 1 — Auth & Governance Core

**Objective:** Solid RBAC (Auth) and System Roles/Policy (Governance) with contracts.

**Auth slice**

* Routes: login/logout/whoami.
* Services: session mgmt only; RBAC decorators present (toggle in dev).
* Contracts: `auth_v2.get_current_user()`, `auth_v2.require_roles(...)` (read‑only helpers).

**Governance slice**

* Models: Officer/Authorizations (seed minimal), RoleCode catalog, US_STATE_CHOICES.
* Services: policy lookup: spending cap, allowed system roles.
* Contracts: `governance_v2.get_authorized_system_roles(entity_ulid)`, `validate_roles(...)`.
* Seeder: role codes, initial officers, US states.

**DoD (P1):** Can fetch allowed system roles via contract; Auth & Governance unit tests pass; seeds idempotent.

---

## Phase 2 — Ledger (formerly Transactions) MVP

**Objective:** Immutable append‑only events with verify.

* Model: `ledger_event` (type, happened_at, actor_id, entity_ulid(s), section, changed_fields (names only), reason, request_id, prev_hash, curr_hash).
* Service: `append_event(event_envelope)`; `verify_chain()` utility; pagination query.
* Contract: `ledger_v2.emit(event_envelope)->EventDTO`.
* CLI: `flask ledger verify` prints OK and first bad index.

**DoD (P2):** Mutations from any slice go through emit; verify script OK; JSON logs include emitted event id.

---

## Phase 3 — Entity Minimal (Testing Level → Stable)

**Objective:** Create & fetch Entity via contract; no PII stored outside owning slice.

* Model: `entity` (ulid, kind, created_at, archived_at nullable).
* Service: create, get, archive (archive only; never delete).
* Contract: `entity_v2.create_entity(payload)->EntityDTO`, `get_entity(ulid)`.
* Route: thin POST to create (dev‑gated), proves ULID and ledger emission.

**DoD (P3):** Creating an entity emits `entity.created` event; archive emits `entity.archived`.

---

## Phase 4 — Resources & Customers (thin vertical)

**Objective:** Minimal capability to register a Resource org and a Customer person, both as Entities, using Governance policy and emitting Ledger events.

**Resources slice (MVP)**

* Model: `resource_org` (ulid FK to entity), capability matrix (jsonb-ish text), status.
* Service: `register_resource(...)` (validates against Governance taxonomy), `classify(...)`.
* Contract: `resources_v2.register(...)` (dry_run/commit) → emits `resource.created`.
* Template: simple read‑only list; form with CSRF.

**Customers slice (MVP)**

* Model: `customer` (ulid FK to entity), minimal non‑PII fields; PII references go to encrypted store later.
* Service: `register_customer(...)` (role check via Governance contract), emits `customer.created`.
* Template: intake stub (no PII beyond allowed minimal fields), CSRF.

**DoD (P4):** Can create one Resource and one Customer end‑to‑end; all via contracts; ledger shows events.

---

## Phase 5 — Sponsors & Finance (stub) + Logistics (stub)

**Objective:** Put boundaries in place without deep logic.

* Sponsors: model stubs + contract for `donation.recorded` (no money flows yet); emits ledger event.
* Finance: placeholder slice (less‑than‑half built) gated by feature flag; no cross‑slice writes.
* Logistics: model for `item_template` + `kit_template` (no fulfillment yet); read‑only inventory list.

**DoD (P5):** Stubs compile; routes hidden behind feature flags; no integration debt added.

---

## Phase 6 — Calendar (project tracking minimal)

**Objective:** Persist simple notes/tasks linked by ULID, show conflict placeholder.

* Model: `calendar_item` (ulid, starts_at, ends_at, title, notes, entity_refs[] text list).
* Service: `schedule_note(...)` with governance override hook (no real conflicts yet).
* Route: list + create with CSRF; StrictUndefined templates.

**DoD (P6):** Can attach a note to a Resource or Customer ULID; emits `calendar.note.added`.

---

## Phase 7 — Web (public UI) shell

**Objective:** Minimal landing page reading from read‑only contracts; zero PII.

* Static assets under `app/static`; templates extend shared layout; no JS required.

**DoD (P7):** Public home renders, links to docs library; no auth required.

---

## Cross‑Cutting Tasks (apply across phases)

* **Migrations:** strict Alembic workflow; all DateTime naive UTC; generate IDs in app layer.
* **Security:** CSRF on all POST forms; RBAC decorators present but disabled in dev; break‑glass path documented.
* **Archival:** add `archived_at` to all major tables; never delete; provide `archive_*` services.
* **Docs Library:** `/docs/` route lists static reference docs (cache TTL knob).
* **Testing posture:**

  * Contract tests (DTO shape, error model) first.
  * Service tests (business logic) second.
  * Route smoke tests last (render 200, CSRF token present).
  * Replace brittle UI tests with contract assertions.

---

## Definition of Done (global checklist)

* [ ] All cross‑slice calls use **Extensions contracts** only.
* [ ] Every mutation path: `dry_run → commit` and emits a single **Ledger** event.
* [ ] JSON logs present for request start/end + event emission with `request_id`.
* [ ] No PII in Ledger or logs; only ULIDs and field names.
* [ ] Jinja **StrictUndefined** active; CSRF present on all forms.
* [ ] Library helpers (`ids`, `chrono`, `models`, `utils`, `jsonutil`, `logging`) are the only primitives used.
* [ ] Feature flags gate unfinished slices; repo compiles with flags off.
* [ ] Verify script passes for the Ledger chain.

---

## Immediate Next 5 Actions (to break inertia)

1. Finalize `lib/jsonutil` public API + tests; integrate in logging scrubber.
2. Wire `lib/logging` domain loggers app‑wide; add request/correlation id middleware; show log sample in README.
3. Lock **Extensions** contract stubs (`*_v2.py`) with DTOs + errors; make emit bus the only mutation path.
4. Promote Entity from "testing level" to stable: create/get/archive services + contract; emit `entity.*` events.
5. Turn off half‑built slices behind FeatureFlags; keep only Auth, Governance, Ledger, Entity, and minimal Web enabled until P4.

---

## Repo Hygiene & Guardrails

* Branch: `v2-cutover` stays green; PRs must include contract tests and ledger event assertions.
* Enforce import rules: slices never import each other; only `extensions` allowed.
* CI lints with Ruff + type checks; test suite splits `contracts/`, `services/`, `routes/`.
* Logs, DB, tmp live under `/srv/vcdb/var/*` in prod posture; dev under `var/app-instance`.

---

## Nice‑to‑Have (after MVP)

* Governance Admin UI (officers/authorizations lifecycle).
* Resource capacity math + SLA timers; Calendar conflict detection with admin override events.
* Reimbursement flow (Sponsors/Finance) with receipts custody events.
* Notes vault encryption and key rotation plan.
