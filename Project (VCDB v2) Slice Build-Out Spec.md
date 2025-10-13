# Project (VCDB v2) Slice Build-Out

- **Stack:** Python 3.12, Flask, Flask-Login, Jinja2, SQLite (dev DB at `var/app-instance/dev.db`).

- **App factory:** `app.create_app("config.DevConfig")`.

- **Blueprints already wired:** `web`, `auth`, plus placeholder “hello” routes for: `customers`, `calendar`, `governance`, `inventory`, `resources`, `sponsors`, `transactions`.

- **Auth status:** Working sessions + login/logout + `/auth/whoami`. Users are in SQLite with `pbkdf2:sha256` hashes. Basic `login_required` in place; RBAC decorators can come later.

- **Data direction:** We’ll eventually use a Party/PartyRole pattern and keep PII in a “core/encrypted” area. For now, slices can be scaffolded without DB writes — just enough to prove routing, page structure, and auth gating.

# What I want in this thread

Please generate **production-grade scaffolding** for each slice, consistent in structure and style, in accordance with Scaffolding Docs software specifications.

1. **Blueprint module per slice**
   
   - Location: `app/slices/<slice>/`
   
   - Files: `__init__.py` (exports `bp`), `routes.py` (register routes), `templates/<slice>/…` (Jinja pages)
   
   - URL prefix: `/<slice>` (e.g., `/customers`, `/inventory`, etc.)
   
   - At minimum, a `GET /hello` route that:
     
     - Requires `login_required`
     
     - (Optional, later) supports `@roles_required("user")`
   
   - Slice-specific models.py, database tables and fields per slice as outlined in Scaffolding Docs specifications. 
   
   - Slices will remain self-contained. Interfaces between slices will live in <slice>/services.py

2. **Navigation + layout**
   
   - Ensure base layout links to each slice: `customers`, `calendar`, `governance`, `inventory`, `resources`, `sponsors`, `transactions`.
   
   - Keep the “Login/Logout” affordance consistent with our current `auth` slice.

3. **Separation of Concerns**
   
   ### What belongs in `app/extensions.py`
   
   Keep this file focused on **app-level adapters** and **cross-cutting utilities** that any slice can import without depending on another slice’s internals:
   
   - **Adapters / singletons**
     
     - `db` (SQLite connector/row factory), `logger` (JSONL), `ulid()` generator
     
     - `policy` registry (reads `authorizations` table to expose knobs, e.g., staff spend cap)
     
     - `event_bus.emit()` → writes to `log_events` (idempotent on `request_id`)
     
     - `idempotency_guard(request_id)` → one-shot insert/lookup
     
     - `clock.now_utc()`, `tz` helpers (business-time calendars/holidays)
   
   - **Validation / normalization**
     
     - `validate_state`, `validate_phone`, `normalize_email` (names-only; no PII logging)
   
   - **Scheduling helpers**
     
     - `calendar_helpers.create_child_event(...)` (scheduling-only; no business logic)
   
   - **Reporting hooks**
     
     - `exports.publish_public_stream(...)` (watermark + manifest + checksum)
   
   - **Auth context shims**
     
     - `current_actor_id()` (pulls actor ULID from session/JWT)
   
   **These are stable, dependency-free** utilities. Slices can import them safely.
   
   ### What stays in each slice (services)
   
   Each slice keeps its **fat services** that own business rules for that area:
   
   - `slices/sponsors/services.py`
     
     - `record_contribution(...)`
     
     - `reimbursement.request/submit/receive/expire(...)`
     
     - `tiers.recompute(now_utc)` (called by nightly job)
   
   - `slices/inventory/services.py`
     
     - `assemble_kit(...)`, `issue_kit(...)`, `start_recon(...)`
   
   - `slices/calendar/services.py`
     
     - `create_event(...)`, `override_conflict(...)`, `attach_resources(...)`
   
   - `slices/customers/services.py`
     
     - `create_customer(...)`, `update_personal/contact(...)`
   
   **These services use** `extensions` (db, policy, event_bus, idempotency_guard) and **emit** ledger events; they don’t import each other directly.
   
   ### Avoiding circular imports (important)
   
   - Slices **never** import other slices. If sponsors needs to schedule a follow-up, it calls a **thin wrapper** in `extensions.calendar_helpers`, not calendar’s service directly.
   
   - Keep `extensions.py` free of business logic; it should orchestrate adapters and provide thin façades only.
   
   ### Example interfaces
   
   - **Ledger (cross-slice):**
     
     - `event_bus.emit(event_type, *, slice, actor_id, target_id=None, entity_ids=None, changed_fields=None, refs=None, amounts=None, request_id, correlation_id=None, happened_at=None) -> ULID`
   
   - **Policy (cross-slice):**
     
     - `policy.get("staff_spend_cap_cents") -> int`
     
     - `policy.get("reimbursement_expiry_days") -> int`
   
   - **Sponsors (slice service):**
     
     - `record_contribution(sponsor_id, kind, amount_cents, valuation_basis, fiscal_year, event_id, request_id, actor_id) -> ULID`
     
     - `reimbursement.request(case_key, authorized_amount_cents, sponsor_id, request_id, actor_id) -> ULID`
     
     - `tiers.recompute(now_utc) -> {"updated": int}`
   
   - **Inventory (slice service):**
     
     - `assemble_kit(kit_template_id, components_override=None, request_id, actor_id) -> ULID`
     
     - `issue_kit(issuance_id, customer_id=None, event_id=None, request_id, actor_id) -> ULID`
   
   - **Calendar helpers (in extensions):**
     
     - `calendar_helpers.create_child_event(parent_event_id, template_code, start_dt_local) -> event_id`
   
   - **Validation (in extensions):**
     
     - `validate_state("CA") -> True`
     
     - `normalize_email(" A@B.c ") -> "a@b.c"`
   
   ### Where slice-specific fields live
   
   - **In the slice**: Field sets, DB access, and rules stay close to the slice (e.g., sponsorship `valuation_basis`, inventory `components_json`).
   
   - **In `extensions`**: Only cross-cutting helpers that *operate on IDs*, not full models. Return simple dicts/ULIDs to avoid tight coupling.
   
   ### How slices will talk to each other
   
   - **Through events, not imports.** A sponsors action emits `reimbursement.requested`; a nightly job (using `extensions`) calls `tiers.recompute`. If calendar needs to create a dependent event, use `extensions.calendar_helpers` to keep coupling low.
   
   - If a truly synchronous cross-slice call is necessary, expose a **thin façade** in `extensions` that delegates to the owning slice via a registered callable (set at app init). That keeps import direction one-way.
   
   ### Conclusion
   
   We keep `extensions.py` as the **stable interface surface** (adapters + façades), and each slice as the **owner of its rules**. This is fully compatible with the structure you’ve approved (vertical slices, skinny routes, fat services), avoids circular imports, and supports clean unit tests and idempotent eventing.

4. **Smoke test script (curl)**
   
   - A single bash script we can run locally that:
     
     - Hits `/healthz` and `/` (expect 200)
     
     - Hits each `/…/hello` unauthenticated (expect 302 -> `/auth/login?next=…`)
     
     - Logs in as `user@example.com` (password: `password`) and confirms each `/…/hello` returns 200
     
     - Logs out and confirms redirect behavior again
   
   - Script should accept `BASE=http://127.0.0.1:5000` env var.

5. **Route dump**
   
   - Include (or keep) a small `dump_routes(app)` helper we can call on startup to print route table and a brief “boot sanity” section (config object, DB path, secret key present, registered blueprints, Flask-Login status).

# Constraints & assumptions

- Keep imports acyclic. Blueprints should **not** import from each other; they may import shared helpers from a neutral module (extensions.py) if needed.

- Keep everything compatible with our current app factory, config and Scaffolding Docs specifications.

- Don’t introduce new frameworks; stay with Flask + Jinja + sqlite3 (for auth already in place).

# Deliverables

- For **each slice**: `__init__.py`, `routes.py`, services.py as required and minimal templates that extends our base layout.

- A short snippet to add in `app/__init__.py` showing how to register each slice blueprint with its prefix (or confirm current pattern).

- Full models.py and foreign key associations for each slice per <slice> scaffolding docs specifications

- A `scripts/smoke_slices.sh` bash script as described.

- Any tiny updates to `templates/layout/base.html` needed for navigation.

# Acceptance criteria

- per <slice> adherence to Scaffolding Docs specifications 

- App starts cleanly (`python manage_vcdb.py`) with route dump showing all slice routes.

- `curl` smoke script passes (302s unauth, 200s post-login).

- No circular imports.

- Code is tidy, consistent, and ready for future endpoints.
