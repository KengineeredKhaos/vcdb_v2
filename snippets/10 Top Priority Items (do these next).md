Love it. Here’s a crisp “what’s still hanging” punch-list, grouped by slice and priority, with concrete next steps + quick checks.

# Top 10 Priority Items (do these next)

1. Governance — Policy files (JSON)
- **Status:** `policy_issuance.json` live + schema + semantics checks working via `flask dev policy-health`.

- **Next:**
  
  - Add schemas + stubs for: `policy_rbac.json`, `policy_domain_roles.json`, `policy_calendar.json` (blackouts/windows), `policy_logistics_states.json` (item lifecycle).
  
  - Wire Admin save route to **validate (schema + semantics) before write**.

- **Quick check:** `flask dev policy-health`
2. Auth ↔ Governance (role boundaries)
- **Status:** Concept pinned: RBAC (Auth) separate from Domain roles (Governance).

- **Next:**
  
  - Place `policy_rbac.json` under `app/slices/governance/data/`.
  
  - Add semantic rule: domain role **civilian** disallows any RBAC.
  
  - Add checker in `policy_semantics` (already scaffolded) and surface WARN/ERROR in `dev policy-health`.
3. Customers — Eligibility snapshot (baseline)
- **Status:** Table + services + tests ✅.

- **Next:**
  
  - Extend snapshot to hold *needs assessment tiers* from Customer Profile (TBD).
  
  - Add CLI to view/set flags for a ULID (handy while UI is WIP).

- **Quick check:** `pytest -q tests/test_customer_snapshot.py`
4. Customers — “Customer Profile” (verification & tiers)
- **Status:** Not implemented, but pinned.

- **Next:**
  
  - Add `customer_profile` table (non-PII enums; verification dates; assessor id).
  
  - Service: `update_profile(...)` emits Ledger event; recompute eligibility snapshot.
  
  - Hook Governance semantics to require veteran_verified for certain rules.

- **Exit test:** unit tests similar to eligibility snapshot.
5. Logistics — Cadence + availability
- **Status:** `available_skus_for_customer(...)` wired; cadence count uses `Issue` table behind a **dev toggle**.

- **Next:**
  
  - Finalize `Issue` model + migrations (even if initially minimal) so cadence runs against DB by default.
  
  - Add `policy_logistics_states.json` + state machine (`transition_item(...)`) with semantic checks (no illegal transitions).

- **Quick check:** `flask dev eligible <ULID>`
6. Catalog — SKU source
- **Status:** Contract exists; temp stubs; one known sample SKU working.

- **Next:**
  
  - Implement `list_skus(active_only=True)` to read from **a seed file** or DB (your call); ensure `classification_key` and SKU patterns align with Governance rules.
  
  - Add schema for catalog SKUs if JSON-backed.

- **Quick check:** small unit test to assert `list_skus()` returns valid `classification_key` set.
7. Calendar — Projects & blackout windows
- **Status:** Blackout check stubbed via contract; dev tests stubbed to “no blackout”.

- **Next:**
  
  - Add `policy_calendar.json` for blackout windows + project funding guardrails.
  
  - Contract `calendar_v2` to read those and expose `is_blackout(project_ulid, when_iso)` + `check_funding(...)`.

- **Quick check:** add a tiny test to flip blackout true/false and confirm Governance blocks/allows.
8. Admin slice — Policy Editor & Health
- **Status:** Basic Admin slice scaffolded; CLI health command exists.

- **Next:**
  
  - Add web form to load/edit/save any policy under `slices/governance/data/` with **pre-save schema+semantics validation** and friendly error surfacing.
  
  - Admin “20-questions” policy editor with JSON linting
  
  - Add a read-only Policy Index page listing all policy files + last modified.

- **Quick check:** manually edit + save a known-bad file → expect validation error toast/log.
9. Entity — “civilian” + POC link/unlink
- **Status:** Civilian concept pinned; POC link/unlink planned.

- **Next:**
  
  - Add ‘civilian’ domain role to seeds + routes to link/unlink entity↔org POC; guard with `get_us_states()` address checks.
  
  - Emit ledger events on link/unlink.

- **Quick check:** minimal service test to assert link emits event and shows up in query.
10. Migrations & test DB hygiene
- **Status:** Baseline + `customer_eligibility` upgrade are working; SQLite batch mode fixed.

- **Next:**
  
  - Add migration for `Issue` (and later `customer_profile`).
  
  - Keep test DB using the temp, writable SQLite URI fixture (we did that).

- **Quick check:** `pytest -q` (should migrate fresh and green)

---

# Nice-to-have (soon after)

- **Finance hooks:** add `check_funding(...)` wrapper that pulls from Finance contract (even a simple “remaining cents” stub) and feed it into Governance `decide_issue(...)` to request approver when over cap.

- **CLI DX:** `flask dev dump-policy --name issuance` → prints validated policy; `--pretty`.

- **UI stubs:** tiny tables + modals for Entities, Governance roster, Calendar windows, Logistics items (already on your plan).

- **Observability:** make sure every policy-changing action emits one Ledger event with `approved_by` where relevant.

---

# Quick sanity commands (today)

- Policy health:  
  `flask dev policy-health`

- Eligible SKUs for a customer:  
  `flask dev eligible 01TESTPLAYGROUNDVET________`

- Tests currently green:  
  `pytest -q tests/test_customer_snapshot.py tests/test_governance_decide_issue_smoke.py`

---

# Suggested 3-step next move

1. **Lock policy surfaces**: add `policy_rbac.json`, `policy_domain_roles.json`, `policy_calendar.json`, `policy_logistics_states.json` (schemas + semantics).

2. **Make cadence real**: add `Issue` model + migration; flip the dev toggle off so cadence counts query DB by default.

3. **Add Customer Profile** minimal table + service; wire into eligibility snapshot and one Governance qualifier (`veteran_required` already works; add `tier1_any_of` against the profile values).

If you want, I can draft the JSON Schemas for those three policy files and the minimal SQLAlchemy models (Issue, CustomerProfile) in one pass so you can drop them in and iterate.
