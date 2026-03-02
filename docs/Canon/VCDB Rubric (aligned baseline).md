# VCDB Rubric (Aligned Baseline)

Here’s a rubric + flow diagram you can keep beside you while you build. It’s
written in “VCDB slice language” (skinny routes, fat services, mappers, DTOs).

Relationship to Ethos:

- This is the desk-side quick reference (“Cliff Notes”).
- It operationalizes VCDB v2 — Ethos & Canon Invariants.
- If anything here conflicts with Ethos, Ethos wins and this file must be fixed.

---

## Non-negotiables overlay (from Ethos)

Keep these in mind while using the rubric:

- Routes/CLI own **commit/rollback**; services may `flush()` only.
- **No cross-slice imports** and **no cross-slice DB reach-arounds**.
- **Contracts are mandatory cross-slice**; they are the only bridge.
- **One boundary invocation = one `request_id`**, minted at boundary, propagated.
- **ULID everywhere**; facets are PK=FK by `entity_ulid`.
- **Ledger has no PII**; every committed mutation emits a Ledger event.
- **No PII outside Entity** (except approved snapshot stores like History/vault).
- **Governance policy never names tables/columns** (no schema leakage).

---

## Rubric: what lives where?

### UI Layer

Templates / Forms

- Purpose: capture input and show output
- Data shape: HTML fields ↔ form objects ↔ view DTOs
- Never: DB writes, joins, business rules, ledger logic

### Route Layer (skinny)

Routes

- Purpose: orchestration + guardrails
- Responsibilities:

  - auth/RBAC checks
  - wizard nonce + PRG
  - call service functions
  - commit/rollback
  - emit Ledger events (only when `changed_fields` non-empty)

- Never: direct SQL/ORM manipulation beyond “call service”

### Service Layer (fat)

Services

- Purpose: business logic + DB interaction
- Responsibilities:

  - validate/normalize inputs (non-form validation)
  - query DB (joins, pagination)
  - mutate DB (create/update)
  - compute derived facts (tier rollups, effective cues)
  - return view DTOs (via mapper) and/or ChangeSetDTO (mutations)

- Never: HTML, request context, redirects
- Never: commit/rollback (boundary owns it)

### Mapper Layer (translation, dumb)

Mappers

- Purpose: convert shapes
- Two common mappings:

  - DB projection → View DTO (safe return shape)
  - Blob dict → EnvelopeDTO (parse label only)

- Never: SQL, request, side effects
- PII: only Entity slice projects PII; other slices’ mappers are non-PII

### Contract Layer (mandatory cross-slice; optional intra-slice)

Extensions Contracts

- Purpose: stable cross-slice interface (DTOs + errors)
- Mandatory when crossing slices (the only bridge)
- Optional within a slice (routes may call services directly inside the slice)
- Never: import other slice models

---

## Flow diagram: request → DB → response (Customer “quick peek”)

```text
[USER] clicks "Customers" page (GET /v2/customers?page=1)

    |
    v

[ROUTE] customers.routes.list()
  - parse query args (page/per_page)
  - (RBAC check)
  - call services.list_customer_summaries(...)
  - render template with returned Page[CustomerSummaryView]
  - (no DB writes, no ledger)

    |
    v

[SERVICE] customers.services.list_customer_summaries(page, per_page)
  - build SQL query (joins Customer + Eligibility + Profile)
  - paginate(query) -> Page[tuple(Customer, Eligibility, Profile)]
  - map tuples -> CustomerSummaryRow  (service-local projection)
  - map row -> CustomerSummaryView    (presentation DTO)
  - return Page[CustomerSummaryView]

    |
    v

[MAPPER] customers.mapper.map_customer_summary(row)
  - just assembles CustomerSummaryView(...)
  - no SQL, no side effects

    |
    v

[ROUTE] renders template
  - Jinja iterates page.items (views)
  - column order controlled by template, not DTO field order

    |
    v

[USER] sees list of customer cards
```

---

## Flow diagram: wizard step (POST) → mutate → PRG redirect

Example: Step C “Needs Tier 1” POST

```text
[USER] submits form POST /v2/customers/<ulid>/needs/tier1

    |
    v

[ROUTE] customers.routes.needs_tier1_post()
  - _wiz_expect_nonce(step, entity_ulid)
    - stale? flash + redirect to wizard_next_step (NO mutation)
  - validate form
    - invalid? re-render (NO mutation)
  - call services.needs_apply_ratings(...)
  - if changed_fields empty:
      - commit (or noop)
      - consume nonce only on success
      - redirect (PRG)
  - if changed_fields non-empty:
      - commit
      - consume nonce
      - emit ledger event (field names only)
      - redirect (PRG)

    |
    v

[SERVICE] customers.services.needs_apply_ratings(...)
  - ensure facet exists / ensure current assessment_version
  - write rating rows (precreated 'na' rows updated)
  - recompute cached tier mins + flag on customer_customer
  - return ChangeSetDTO(changed_fields=[...], is_noop=...)

    |
    v

[MAPPER] (optional)
  - if service returns view DTOs, mapper maps
  - otherwise returns ChangeSetDTO only

    |
    v

[ROUTE] redirect to GET next step
  - GET renders view DTOs for confirmation
```

Key rule: **Routes commit + ledger. Services flush.**

---

## “Cheat sheet” mapping of DTO types to layers

- `CustomerSummaryRow`
  ✅ service-local projection (DB → service)

- `CustomerSummaryView`
  ✅ outward-facing view DTO (service → route/template/contract)

- `EnvelopeDTO`, `ParsedHistoryBlobDTO`
  ✅ parse/validate envelope label (service utility) and cache columns

- `ChangeSetDTO` (or similar)
  ✅ mutation result: `changed_fields`, `created`, `noop`

---

## One mental trick that helps a lot

Ask: **“Who owns the truth?”**

- DB truth → services query it
- Business truth / decisions → services compute it
- Audit truth → routes emit ledger (after commit)
- Display truth → templates decide column order and presentation
- Cross-slice truth exchange → contracts + DTOs (ULIDs + safe snapshots)

---

## Dataset Planning Template

Use this when building a new page/dataset:

```text
Dataset Name:
Audience:
User question it answers:
Tables (source of truth):
Filters:
Sort:
Pagination: yes/no

Service function:
- Inputs:
- Query (joins):
- Derived fields:
- Mutations: yes/no
- Returns: Page[ViewDTO] OR ViewDTO OR ChangeSetDTO

Row DTO (DB → service):
View DTO (service → route/template):
Template:
Ledger emit: (event type + changed_fields policy)
```

---

## Dataset catalog for Customers (starter)

### 1) Customers List

User expectation: “Show me customers; let me filter/sort/search.”

- Audience: staff (admin sees same + maybe extra columns)
- Tables: `customer_customer` (+ left join `customer_eligibility`,
  `customer_profile`)
- Filters: status, needs_state, watchlist, tier1_min, veteran_status,
  homeless_status
- Sort: `customer_customer.updated_at desc` (or `entity_ulid` fallback)
- Pagination: yes (`Page[...]`)
- Row DTO: `CustomerSummaryRow` (joined projection)
- View DTO: `CustomerSummaryView`
- Template: table of cards/rows (column order defined in HTML)

### 2) Customer Overview Page

User expectation: “Quick peek at this entity_ulid.”

- Audience: staff
- Tables: same joins as list, plus maybe recent history count
- Derived fields: “effective cues” (watchlist affecting effective tier1)
- Row DTO: `CustomerOverviewRow`
- View DTO: `CustomerOverviewView` (a richer card than list)
- Template: single card + action links (Start/Resume intake, Needs, History)

### 3) Eligibility Editor (wizard step or standalone)

User expectation: “Set veteran/homeless status, branch, era.”

- Audience: staff (admin override rules later if needed)
- Tables: `customer_eligibility` (+ `customer_customer` to drive intake_step)
- Mutates: yes
- Service returns: `ChangeSetDTO(changed_fields, is_noop, created)`
- Route: nonce/PRG + commit + ledger emit only if changed_fields non-empty
- Ledger event: `customer.eligibility.updated` (field names only)

### 4) Needs Assessment (Tier 1/2/3)

User expectation: “Rate categories; app computes tier minima; allow skip.”

- Audience: staff
- Tables: `customer_profile`, `customer_profile_rating`, `customer_customer`
  (cached rollups), optionally `customer_history` snapshot on reassess
- Mutates: yes
- Flow: begin/in_progress → update ratings → complete or skip
- Row DTO: for GET you can use `NeedsAssessmentRow` (current version + 12 ratings)
- View DTO: `NeedsAssessmentView` (safe to render)
- Ledger: per step only if changed_fields non-empty

### 5) Customer History Timeline “Quick Peek”

User expectation: “What’s been tried before? Avoid duplicates.”

- Audience: staff
- Tables: `customer_history` only
- Columns used: cached envelope columns (`title`, `summary`, `severity`,
  `public_tags_csv`, `happened_at`, `source_slice`, `source_ref_ulid`)
- Filters: kind, source_slice, tags (public only), date range
- Row DTO: `HistorySummaryRow`
- View DTO: `HistorySummaryView`
- Template: timeline list (never show admin tags)

### 6) History Details Page

User expectation: “Open this entry and see more.”

- Audience: staff
- Tables: `customer_history`
- Rule: show envelope + payload JSON prettified only if safe/simple; otherwise
  link out to producer slice detail view using `source_slice/source_ref_ulid`.
- View DTO: `HistoryDetailView` (envelope + payload as dict/string)

### 7) Admin Integrity Inbox (sweep results)

User expectation: “Show me review flags like high-frequency requests.”

- Audience: admin only
- Tables: either `admin_alert` (preferred) or direct sweep view over
  `customer_history where has_admin_tags=true`
- Sort: happened_at desc
- View DTO: `AdminAlertView` (ULIDs + reason codes, no PII)
- Template: admin queue

---

## Suggested build order (keeps momentum)

1. Customers List (dataset #1)
2. Customer Overview (dataset #2)
3. History Timeline (dataset #5)
4. Eligibility Step (dataset #3)
5. Needs Assessment (dataset #4)
6. History Details (dataset #6)
7. Admin Inbox (dataset #7)

That sequence gives you early UI value and forces the projection/mapping pattern
to stabilize before mutations get complicated.

---

## Tickler rule (keep Ethos + Rubric aligned)

When adding or changing Ethos:

1. If you added a new **non-negotiable invariant**, add it to the overlay list at
   the top of this file.
2. If you added a new **implementation pattern**, update the rubric layer
   responsibilities and/or a flow diagram.
3. If you added a new **UI dataset**, add a dataset card (catalog) and/or
   update the Dataset Planning Template.

When adding something to the rubric that looks like a non-negotiable rule:
promote it into Ethos first, then reference it here.
