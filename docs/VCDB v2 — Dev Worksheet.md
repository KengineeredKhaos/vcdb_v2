# VCDB v2 — Focused TODO Phases

Use each phase below as the opener for a dedicated chat thread.

---

---

---

## Phase 3 — Admin as the control surface

**Opener:**  
Define Admin as the control surface for Governance, Finance, and Ledger so operator authority and infrastructure-only slices have a clean boundary.

### Scope

- Specify which read/edit/review actions belong in Admin.
- Specify which slices remain infrastructure-only.
- Define Admin vs Auditor access boundaries.
- Consolidate slice-specific Admin inboxes into the Admin slice.
- Wire queue/provider reads through versioned Extensions contracts.
- Keep queue rows PII-free and resolve names only at render time via Entity cards.

### Why this phase follows queue v1

Once the queue exists, this phase decides where operational control really lives. :contentReference[oaicite:2]{index=2}

---

## 

---

## Phase 5 — Ledger resilience and pre-live hardening

**Opener:**  
Harden Ledger failure semantics and degraded-mode behavior before live deployment.

### Scope

- Implement `EventHashConflict`.
- Implement `ProviderTemporarilyDown`.
- Define:
  - reject vs idempotent-accept behavior
  - audit/meta recording
  - retry/rollback policy
  - operator-visible diagnostics for CLI/HTTP flows
- Review `event_bus -> ledger_v2` degraded-mode behavior.
- Replace temporary generic exception handling around Ledger/provider writes with explicit semantics once the money path is complete.

### Why this is a pre-live phase

This is critical reliability work, but it is best done after the route/admin seams are less in flux. 

---

## Phase 6 — Customer reassessment policy

**Opener:**  
Define Governance policy for time-based Customer needs reassessment.

### Scope

- Define reassessment interval(s) and triggers.
- Define what constitutes overdue status.
- Decide where the system surfaces reassessment due:
  - CustomerDashboard banner
  - optional Admin sweep/advisory path
- Implement mechanics after policy exists:
  - read-only due computation
  - UI banner and “Begin reassessment” action
  - reassessment-start snapshot behavior
- Ensure no spam:
  - snapshot only on reassessment start
  - not on every `needs_set_block()`

### Why this is later

Important, but not on the same critical path as route truth, Admin queue shape, and Ledger resilience. :contentReference[oaicite:5]{index=5}

---

## Phase 7 — Logistics physical inventory reconciliation

**Opener:**  
Design the physical inventory reconciliation workflow and its audit trail.

### Scope

- Add admin-only ledger event `logistics.inventory.reconciled`.
- Add `logi_inventory_snapshot`.
- Define:
  - CSV snapshot hashing
  - before/after/diff metadata
  - project linkage
  - storage boundaries between Ledger vs Logistics/Calendar artifacts
- Keep item-level details out of Ledger.

### Why this is later

Well-scoped and meaningful, but it can wait until admin/ledger infrastructure is more settled. :contentReference[oaicite:6]{index=6}

---

## Phase 8 — Future Dev documentation cleanup

**Opener:**  
Document the Dev Portal utility in the Future Dev Toolkit.

### Scope

- Document purpose, scope, and guardrails.
- Explain dev/test-only behavior.
- Document:
  - cold-call GET sitemap role
  - smoke/probe behavior
  - exclusions
  - status legend
  - safety limits
- Make clear it is a safe dev/test utility, not a workflow-driving surface.

### Why this is last

Valuable, but it should follow the system hardening work it is meant to describe. :contentReference[oaicite:7]{index=7}

---

# Recommended working order

1. Phase 3 — Admin as the control surface   
2. Phase 5 — Ledger resilience and pre-live hardening  
3. Phase 6 — Customer reassessment policy  
4. Phase 7 — Logistics physical inventory reconciliation  
5. Phase 8 — Future Dev documentation cleanup

That’s a solid pre-beta slate, and the framing is much cleaner now.

I’d treat them as five separate workstreams with this order:

1. **Phase 3 — Admin oversight surface / Admin Dashboard**  
   Lock what Admin and Auditor can see and do, and what remains indirect through contracts. This gives the rest of the threads a stable access model.

2. **Phase 5 — Ledger resilience, auditor drill-down, health checks**  
   This is your pre-live reliability fence. It also clarifies what Admin/Auditor drill-down actually means in practice.

3. **Calendar — staff Project Status Report with financial status**  
   Once the access model and ledger/finance health posture are clearer, you can define a safe staff-facing projection instead of exposing raw Finance/Ledger internals.

4. **Logistics — staff inventory management / resupply UI**  
   This is direct operator workflow and should be shaped as a mission surface, not an audit surface.

5. **Logistics — admin/auditor anomaly drill-down**  
   This comes after the staff flow, because anomaly inspection makes more sense once the normal stock/resupply workflow is stable and visible.

The nice thing is that each thread now has a different question at its core:

- **Thread 1:** What is Admin/Auditor allowed to see and do?

- **Thread 2:** How does Ledger fail, recover, and report health?

- **Thread 3:** What safe financial/ledger projection should staff see inside Calendar?

- **Thread 4:** What does normal day-to-day Logistics work look like for staff?

- **Thread 5:** What anomaly, drift, and audit views do Admin/Auditor need for Logistics?

- **Thread 6:** Ledger Slice Mop-up
  
  1. Ledger cron integration
     
     - scheduled daily close
     - cron tattle-tail
     - failure_cron_ledgercheck owned by cron/runtime status
  
  2. Auditor drill-down
     
     - read-only views for LedgerAdminIssue
     - LedgerHashchainCheck
     - LedgerHashchainRepair
     - LedgerEvent chain views
  
  3. Backup/archive integration
     
     - actual backup command calls require_routine_backup_allowed()
     - dirty forensic backup naming and logging
  
  4. Route access tests for Ledger admin/auditor surfaces
     
     - admin can repair/close
     - auditor can inspect only
     - staff cannot access
