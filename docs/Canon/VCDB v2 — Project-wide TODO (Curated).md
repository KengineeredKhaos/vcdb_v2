# VCDB v2 — Project-wide TODO (Curated)

This is a cleaned queue derived from the current project-wide TODO notes.

It is grouped by purpose so the backlog reads like a plan instead of a pile.

Status markers:

- [ ] todo

- [~] in progress

- [x] done

---

## 1) Pre-production guardrails and resilience

- [ ] Ledger hardening:
  
  - implement `EventHashConflict`
  - define reject vs idempotent-accept behavior
  - capture audit/meta fields for those cases

- [ ] Ledger/provider outage handling:
  
  - implement `ProviderTemporarilyDown`
  - normalize contract mapping
  - define retry/rollback behavior
  - surface operator diagnostics

- [ ] Audit resilience pass:
  
  - review degraded-mode behavior around `event_bus -> ledger_v2`

- [ ] Pre-live hardening sweep:
  
  - replace temporary generic exception handling around ledger/provider writes
    with explicit semantics

- [ ] Timestamp canon unification:
  
  - audit model timestamp fields
  - classify DB vs wire/log timestamps
  - convert DB storage to canonical naive UTC
  - update migrations, tests, fixtures, and helpers together
  - treat this as a pre-production gate

---

## 2) Cross-slice integrity and architecture hygiene

- [ ] Audit mutating services for transaction-boundary drift.
- [ ] Audit cross-slice imports and replace reach-arounds with contracts.
- [ ] Define and test auth-mode boundaries for dev vs real access control.
- [ ] Route/template integrity sweep.
- [ ] Add a pagination smoke test.
- [ ] Template audit for CSRF macro on POST.

---

## 3) Access control and Admin control-surface work

- [ ] Define the route-access matrix by slice and role.
- [ ] Harden access control slice-by-slice and add permission tests.
- [ ] Define Admin as the control surface for Governance, Finance, and Ledger.
- [ ] Replace generic inbox/message concepts with a typed Admin work queue.
- [ ] Consolidate slice-specific Admin inboxes into the Admin slice.
- [ ] Define minimal Admin alert storage and UI.
- [ ] Implement the Admin sweep job for CustomerHistory admin tags.
- [ ] Clarify the inbox evolution path.

---

## 4) Calendar, Governance, and Finance follow-through

- [ ] Remove the old `preview_funding_decision` backward-compat shim once all
  
      callers are explicit about `ops_support_planned`.

- [ ] Revisit Calendar task taxonomy and realign finance hints to canonical
  
      Governance policy semantics.

- [ ] Restore a focused seam test for encumber preview op.

- [ ] Revisit Finance handling of `FundingDemandContextDTO`.

- [ ] Revisit Calendar Project/Task planning, synthesis, and demand development.

- [ ] Document the explicit procedure for adding a new finance semantic key
  
      end to end.

---

## 5) Customer and lifecycle policy work

- [ ] Clean up the `customers_v2` contract and keep it small and stable.
- [ ] Add Governance policy for time-based Customer needs reassessment.
- [ ] Generate a strip-map of the Entity Wizard flow.

---

## 6) Logistics and archive lifecycle

- [ ] Add admin-only ledger event `logistics.inventory.reconciled`.
- [ ] Add `logi_inventory_snapshot` table and file/hash metadata path.
- [ ] Land `records_lifecycle` policy cleanly.
- [ ] Land archive package policy and matching schema.
- [ ] Define archive request / approval flow.
- [ ] Build archive jobs:
  - `archive.ledger.yearly`
  - `archive.finance.yearly`
  - later on-demand inactive Resource / Sponsor / User archive jobs

---

## 7) Security and governance authority cleanup

- [ ] Keep RBAC helpers/decorators as the route-level access standard.

- [ ] Retain domain-role helpers only for true entity domain roles.

- [ ] Remove or deprecate use of `governor` as if it were an ordinary
  
      entity-domain role.

- [ ] Add and standardize the two-step pattern:
  
  1. RBAC check
  2. governance authority check

- [ ] Add a dedicated Governance authority helper/contract.

- [ ] Standardize assignment/rescind routes for governance authority.

- [ ] Document bootstrap and break-glass recovery paths.

- [ ] Update stale docs and examples that imply `governor` is a domain role.

---

## 8) Documentation maintenance

- [ ] Keep canon in the Ethos document.

- [ ] Keep system explanation in the System Shape guide.

- [ ] Keep access planning in the Access/Admin document.

- [ ] Keep this TODO file atomic and current rather than appending long-form
  
      narrative notes into canon documents.

- [ ] @TODO(app/__init__.py cleanup, post-security-sweep / pre-beta-freeze)

- Keep this file boring. It should remain a thin app-factory shell, not a
    second control surface or policy engine.

- Cleanup / refit items to revisit after current security hardening:
  
  - 1) Blueprint registration strategy
       
       - All blueprints are currently registered unconditionally.
       
       - Hidden-from-menu is not the same as unreachable.
       
       - Revisit whether unfinished slices should be config-gated at boot or
         whether full route hardening alone is the intended protection model.
  
  - 2) Admin-role helper deduplication
       
       - user_is_admin() and _is_admin_user() duplicate role-check logic.
       
       - Move toward one canonical helper/facade for admin-role checks.
  
  - 3) Stub-auth scaffold cleanup
       
       - Keep stub auth strictly fenced to development/testing only.
       
       - Revisit whether any remaining convenience behavior should be reduced
         further once route-security work is complete.
  
  - 4) admin_alerts() coupling
       
       - admin_alerts() currently reaches directly into admin_cron_status via
         SQL in the app factory layer.
       
       - Revisit whether this should move behind an Admin-owned
         helper/service or other read seam.
  
  - 5) Empty / placeholder seams
       
       - _bind_contracts() is currently empty.
       
       - Either remove it or document its intended purpose clearly.
  
  - 6) Import / structure audit
       
       - Revisit stale or no-longer-needed imports after security 
         sweep settles.
       
       - Keep boot order explicit: config -> logging -> extensions ->
         csrf/jinja -> blueprints -> context processors -> error handlers ->
         cli.
  
  - 7) Factory-size / readability pass
       
       - Consider splitting large local sections into small private helpers
         if this file grows further. 
         
         - Goal: preserve one readable app-construction path with minimal
         
            drift.

- Non-goal for this TODO:
  
  - Do not reopen broad refactors during the current route-security pass.
  
  - Finish the security sweep first, then revisit cleanup with tests green.
