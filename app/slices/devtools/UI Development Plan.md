# VCDB v2 UI Development Map

## 0) Purpose

Build VCDB v2’s web UI **without architectural drift** by enforcing:

- slice ownership (UI hits only slice routes; slices call other slices only via contracts),

- DTO-driven rendering (no direct model reach-through),

- consistent page patterns (list/detail/forms/wizards),

- and a phased build that starts with the shell + read-only views.

---

## 1) Global UI Guardrails (Non-Negotiables)

**Template & safety**

- Jinja `StrictUndefined` everywhere.

- Always include CSRF on POST forms.

- Inline field errors under each input.

- Environment banner always visible (DEV / TEST / PROD).

- Never log or display PII in debug views; use ULIDs + DTOs only.

**Slice boundaries**

- UI talks only to its slice routes; cross-slice is via contracts only.

- No hard-coded select options in templates; all choices come from contracts.

**Forms & validation**

- All mutating views use WTForms/Flask-WTF (no ad-hoc `request.form[...]`).

- Validation layers, in order: browser hints → WTForms → contract require/checks → service/business rules.

- Use one shared Jinja macro for fields (label/input/help/errors).

---

## 2) Template placement + shared layout rule

- Slice templates live here: `app/slices/<slice>/templates/<slice>/*.html`

- Shared layout/partials only here: `app/templates/layout/` (no slice logic).

**Minimum shell**

- `layout/base.html` with `{% block content %}`

- `layout/_nav.html`, `layout/_flash.html`, `layout/_footer.html`

---

## 3) Standard page patterns (use everywhere)

### 3.1 Index/List

- Search + filters (name/status/date window)

- Results table + pagination

- “New …” action only if actor allowed

### 3.2 Detail

- Header: label/name + status + ULID visible

- Primary actions: Edit / New Task / View Ledger / Attachments

- Sections (tabs or vertical): Summary / Profile / History+Ledger / Attachments / Related

### 3.3 Wizard (only when truly multi-step)

- Back / Next / Cancel

- Progress indicator

- Clear save-point rules (draft vs committed)

---

## 4) Cross-cutting UI components (build once, reuse)

1. **Field macro + error block** (your canon)

2. **Pagination macro** (shared)

3. **Environment banner** (DEV/TEST/PROD)

4. **Role/Domain badge chips** (staff/admin/governor/customer/resource/sponsor)

5. **History / Ledger panel** (read-only)

6. **Attachments panel** (drop-in on Customer/Resource/Sponsor/Project/Finance/Ledger)

---

## 5) DevTools vs Admin UI (separate them)

### DevTools (dev-only)

- Prefer CLI; any web DevTools must be admin-only and disabled in PROD.

- Explicit “NO BACKDOORS”.

### Admin UI (operational)

- Governance policy read/edit workflow (dry-run validation, publish)

- User creation + RBAC assignment

- Domain role assignments + officers/pro-tem

- Audit views (Ledger + Journal + combined)

---

## 6) Slice UI backlogs (sanitized)

### 6.1 Auth

- Login/logout

- Login failure

- whoami widget

- password reset/change

- session timeout behavior

- user activity audit

### 6.2 Customers

- Intake wizard (identity/contact → eligibility → needs triage → referral → logistics issuance)

- Customer profile (summary, needs profile, attachments, related)

- Case review “combined view” (ledger, logistics, referrals, finance, calendar)

### 6.3 Resources

- Index (filter by classification/status; link docs)

- Create wizard

- Profile + POCs + SLA/MOU tabs

### 6.4 Sponsors

- Create + profile + POCs + MOU

- CRM suite (interactions, pledges, recognition) .

### 6.5 Calendar

- Calendar views (day/work-week/month, project categories)

- Project create

- Task create

- Budget projection

- Scheduling + conflict resolution

### 6.6 Logistics

- Inventory inspection (SKU + on-hand + quarantined)

- Restock order create

- Receiving

- Issuance wizard (from Customer or from SKU)

- Issuance history

### 6.7 Attachments

- Global index + search (filename/type/tag/linked entity)

- Embedded “Attachments” panel everywhere

- Upload metadata: category + linked primary entity + preview

### 6.8 Static docs library

- Index, categories, simple search, access rules, versioning, cross-links

---

## 7) Wizards

### 7.1 Customer Intake Wizard

1. Search for existing entity (avoid duplicates)

2. Create/confirm identity (ULID shown)

3. Eligibility verification

4. PII intake (address/contact)

5. Needs profile intake

6. Resource referral

7. Logistics issuance handoff

---

### 7.2 Resource Intake Wizard

1. Entity creation

2. Capability profile

3. SLA/MOU requirements

4. POC association (civilian person entity + contacts + relationship)

---

### 7.3 Sponsor Intake Wizard

1. Entity creation

2. Donor/CRM profile

3. SLA/MOU requirements

4. POC association (civilian person entity + contacts + relationship)

---

### 7.4 Logistics Issuance Wizard

Start from **Customer** or **SKU**.
Steps:

1. Select customer

2. Select item/SKU

3. Run contract/policy checks (cadence, eligibility)

4. Confirm & issue (writes Ledger + Logistics)

5. Restock planning (optionally spawns a Calendar task)

---

## 7.5 Finance Wizard Suite

### Wizard A — Fund Intake (Donation or Grant)

Matches your list.

1. Choose intake type: Donation / Grant

2. Capture source + sponsor linkage (sponsor ULID)

3. Capture constraints/conditions (restricted/unrestricted; caps; eligibility tags; reporting requirements)

4. For grants: choose mode (upfront vs reimbursement)

5. Create Fund record (status = **pending** if policy requires)

6. Auto-create any follow-up tasks (especially for reimbursement packets)

**Output:** fund_ulid + constraint summary DTO (safe to display).

### Wizard B — Commit Fund to a Project (Calendar-driven “spend planning”)

This reconciles: “Fund Committed → Project link → Sponsor link”

1. Select Project (calendar project/task context)

2. Select Fund/bucket

3. Enter intended amount + purpose

4. Run **policy check** (caps, allowed categories, governor approval threshold)

5. If approval required → set status “quarantine pending governor auth”

6. If approved/allowed → status “committed” and visible in project budget

**Key rule:** Sponsors do not “spend.” Calendar projects consume plan + execution. Finance records the money movements.

### Wizard C — Spend / Expense Logging (two-step by design)

**Step 1: Preview Spend Decision (no writes)**

- Choose project/task

- Choose fund/bucket

- Enter amount, category, vendor/payee (PII-safe display), and date

- Run policy + budget availability checks

- Return: ok/deny + reasons + “approval required?” + what will be written

**Step 2: Commit Expense (writes)**

- If ok and user confirms:
  
  - write finance journal expense entry
  
  - emit ledger event (no PII; ULIDs + field names)
  
  - optionally create attachments placeholders (receipt needed)

### Wizard D — Reimbursement/Reconciliation (if grant is reimbursement)

Directly maps your “Grant Reimbursement/Reconciliation” bullet.

1. Choose reimbursement-grant fund

2. Show eligible expenses (by fund, project, date window)

3. Assemble packet checklist (receipts, forms, cover sheet)

4. Mark submitted (date + tracking ref)

5. When reimbursed, record income against the same fund + close loop

---

## 8) Build order (unified phase plan)

### Phase 1 — Shell & Auth

- base/nav/flash/footer + env banner

- login/logout + whoami

- static docs landing page

**Done when:** you can log in/out and see role badges + env banner on every page.

---

### Phase 2 — UI Infrastructure + Read-only Admin/Governance

- field macro + base form + CSRF conventions

- select-field loading pattern from contracts

- read-only governance policies + read-only ledger/finance summaries

**Done when:** you can render governance policy index/detail from DTOs, with pagination/search patterns ready.

---

### Phase 3 — Core operational read-only → then mutate

For each slice: build **Index + Detail** (DTO-only) first, then create/edit.
Start with:

- Calendar (projects/tasks views)

- Customers (index/profile/case view)

- Resources (index/profile)

- Sponsors (index/profile)

---

### Phase 4 — Money & Logistics

- Finance Journal UI (income/expense)

- Logistics SKU/items + issuance wizard

- Unfunded requirements + quarantine/approval views

---

### Phase 5 — Sponsors & CRM

- CRM notes/interactions/recognition

- Sponsor metrics (read-only, no spend controls)

---

### Phase 6 — Attachments + cross-slice “case view”

- Attachments UI fully wired

- Conflict resolution tooling + dashboards + case view polish

---

## 9) Lightweight UI testing (minimum set)

- Smoke test: `GET /` renders shell, env banner present, nav hides admin links without admin+governor

- Snapshot-ish tests: governance policy JSON → template rendering (read-only, no mutation)

---

## 10) Future Expansion
