# Canonizing Foundation Checklist

Here’s a short, do-once list so we can stamp the phase complete and move on:

1. **Pin tests (no flake)**
   
   - Keep `tests/foundation`:
     
     - `test_devtools_smoke.py` (health/db, session, whoami header stub)
     
     - `test_ledger_chain.py` (bus→ledger, continuity, determinism, PII-free)
     
     - `test_ledger_immutable.py` (triggers block UPDATE/DELETE)
   
   - In `pytest.ini`, keep random order (or remove noise) but ensure foundation pack runs green in any order.

2. **DTO freeze for v2 GET contracts**
   
   - Add a tiny test that imports each v2 GET contract and asserts response keys match the pinned DTOs (no writes, no PII).
   
   - This gives us “contracts (GET) stability” from your foundation goals.

3. **Governance describe()**
   
   - Expose `governance_v2.describe()` (rbac/domain role catalogs, issuance defaults)
   
   - Add a test that asserts catalogs load and validate (already have policy-health via CLI; just pin a read-only service/route response).

4. **Request/DB hygiene**
   
   - One micro-test that opens a request, checks FK pragma ON (SQLite), then ensures session is clean after request (no pending/dirty).
   
   - You already expose `/api/dev/health/session` → just pin it.

5. **Echo banner ENV fix**
   
   - Swap your `ENV=?` banner to read `current_app.config.get("ENV") or os.getenv("VCDB_ENV")`.

6. **Docs nudge**
   
   - Add a short “Foundation Inspection” section to README: what’s pinned, how to run seeds/tests, and the two env helpers (your `vcdb` and `vcdbt`).

## Nice-to-have (fast)

- **CLI: `flask ledger verify --chain <key>`** (you already shipped verify; chain filter’s handy).

- **Devtools scaffolding (no behavior yet)** for the future repair tool:
  
  - `POST /api/dev/ledger/repair/dry-run` (admin+governor)
  
  - `POST /api/dev/ledger/repair/apply` (admin+governor)
  
  - Both will call analysis later; for now they can return `{"ok": false, "reason": "not_implemented"}` and enforce RBAC.

Once those are set, I agree—UI routing & templating becomes the easy part. Want me to hand you a tiny test that freezes the v2 GET DTO shapes next, or a barebones devtools repair endpoint with the RBAC guard only?
