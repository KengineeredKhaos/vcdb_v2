# Slice_Build_Out Plan/Status 9/23/2025

# Proposed slice order (and why)

1. **Auth** ✅ (done)

2. **Governance** ✅ (policy + admin)

3. **Transactions** ✅ (ledger sink + verify/export)

4. **Resources** → foundational catalog of things you’ll reference everywhere (rooms, venues, gear, staff time buckets, service capacities).

5. **Customers** → people/orgs you serve; needed for sponsorship attribution and later special-event attendance/beneficiary linking.

6. **Sponsors** → funding entities + contributions + reimbursement rules; depends on Customers (Party/PartyRole) and emits finance events.

7. **Inventory** → optional before Calendar, but if your events issue kits/resources, having this next gives you a real operational loop.

8. **Calendar.SpecialEvents** → last; composes Resources + Customers + Sponsors under Governance policy (spend cap, windows).

9. **Web** (public) → can iterate anytime; mostly UI.

Dependency graph (minimal imports, event-driven):

```
Governance  ──policy/enforcers──► Extensions.facades ◄── Transactions.sink
      ▲                                          ▲
      │                                          │
Sponsors, Inventory, Resources, Customers ───────┘
                ▲
                │
            Calendar.SpecialEvents (last)
```

# Per-slice build checklists

Below are tight “definition of done” bullets so each slice is shippable and testable.

---

## 4) Resources

**Models**

- `resources_resource` (id ULID, code, name, type, attributes_json, status)

- `resources_location` (id, name, address fields, tz)

- `resources_assignment` (id, resource_id FK, window_start_utc, window_end_utc, refs: event_id/issuance_id)

**Services**

- `create_resource(code, name, type, attrs, request_id, actor_id)`

- `assign(resource_id, window_start_utc, window_end_utc, refs, request_id, actor_id)` (conflict check optional)

- `release(assignment_id, request_id, actor_id)`

**Routes**

- `GET /resources/hello`

- `GET /resources/list` (simple table)

- `POST /resources/create` (minimal form)

**Events**

- `resources.resource.created`

- `resources.assignment.created`

- `resources.assignment.released`

**Policy hooks (optional now)**

- none required yet (future: max concurrent assignments, blackouts)

**Templates**

- list + create form; reuse pagination macro.

**Smoke**

- unauth redirects; auth 200

- create resource → event in ledger

- assign/release → events emitted

---

## 5) Customers

**Models** (Party pattern lite)

- `party_person` (id, first/last, email, phone, normalized fields)

- `party_contact` (id, party_id FK, kind, value, is_primary)

- `party_role` (id, party_id FK, role_code e.g., “customer”, “sponsor_contact”)

**Services**

- `create_customer(person_fields, request_id, actor_id)`

- `update_contact(party_id, contact_fields, request_id, actor_id)`

**Routes**

- `GET /customers/hello`

- `GET /customers/list`

- `POST /customers/create`

**Events**

- `customers.created`

- `customers.contact.updated`

**Policy hooks**

- validation helpers from `extensions` (normalize_email, validate_phone/state)

**Templates**

- list + create.

**Smoke**

- create → shows in list; ledger has `customers.created`

---

## 6) Sponsors

**Models**

- `sponsors_sponsor` (id ULID, name, category, status)

- `sponsors_contribution` (id, sponsor_id FK, kind, amount_cents, valuation_basis, fiscal_year, refs.event_id?)

- `sponsors_reimbursement` (id, sponsor_id FK, authorized_amount_cents, status, expires_at_utc)

**Services**

- `record_contribution(sponsor_id, kind, amount_cents, valuation_basis, fiscal_year, event_id, request_id, actor_id)`

- `reimbursement.request(case_key, authorized_amount_cents, sponsor_id, request_id, actor_id)`
  
  - **enforcer**: `enforcers.spend_cap(...)` (already registered by Governance)

- `reimbursement.submit/receive/expire(...)`

- `tiers.recompute(now_utc)` (nightly callable; stub is fine now)

**Routes**

- `GET /sponsors/hello`

- `POST /sponsors/contribution` (tiny form)

**Events**

- `sponsors.contribution.recorded`

- `sponsors.reimbursement.requested/submitted/received/expired`

**Policy hooks**

- `policy.require("reimbursement_expiry_days", cast=int, …)`

- `enforcers.spend_cap(amount_cents, ...)`

**Smoke**

- record contribution → ledger event

- reimbursement.request with > cap → 403/PolicyError + `policy.violation` in ledger

---

## 7) Inventory (optional before Calendar, but recommended)

**Models**

- `inventory_kit_template` (id, code, components_json)

- `inventory_kit` (id, template_id, status)

- `inventory_issuance` (id, kit_id, customer_id nullable, event_id nullable, status)

**Services**

- `assemble_kit(template_id, components_override, request_id, actor_id)`

- `issue_kit(issuance_id, customer_id=None, event_id=None, request_id, actor_id)`

- `start_recon(kit_id, request_id, actor_id)`

**Events**

- `inventory.kit.assembled`

- `inventory.kit.issued`

- `inventory.kit.recon_started`

---

## 8) Calendar.SpecialEvents (last)

**Models**

- `calendar_event` (id ULID, kind="special", title, start/end UTC, location_id FK, budget_cents, status)

- `calendar_event_resource` (id, event_id, resource_id, window_start/end)

- `calendar_guest` (id, event_id, customer_id)

**Services**

- `create_event(title, start, end, location_id, budget_cents, request_id, actor_id)`
  
  - **call** `enforcers.spend_cap(budget_cents, extra={"context":"calendar.special_event"})`
  
  - **call** `extensions.calendar_helpers.create_child_event(...)` later as needed

- `attach_resources(event_id, resource_ids, request_id, actor_id)`

- `override_conflict(event_id, assignment_id, reason, request_id, actor_id)`

**Events**

- `calendar.special_event.created`

- `calendar.special_event.resources.attached`

- `calendar.special_event.conflict.overridden`

**Smoke**

- creating event > cap blocked + violation logged

- ≤ cap succeeds and emits created

---

# Milestones & merges

- **M1 (Resources + Customers)**: end-to-end data flow; ledger events visible; list/create UIs.

- **M2 (Sponsors)**: contributions + reimbursement policy enforcement; violation logging.

- **M3 (Inventory)**: kit assemble/issue cycle for richer demos.

- **M4 (Calendar.SpecialEvents)**: compose prior slices; policy-gated budget; resource attachments.

# Routing & nav (already aligned)

- Keep `GET /<slice>/hello` auth-gated per slice.

- Each slice gets `list` and minimal `create` routes/forms; all extend the lean `base.html`.

- Keep smoke scripts updated to hit `/list` and `POST /create` endpoints per slice.

# Ledger hygiene (unchanged)

- Every service emits a single, idempotent event per operation (`request_id` guard).

- Timestamp normalized to UTC (aware → sink normalizes).

- Hash chain verified via `/transactions/verify`.

---

If you want, I’ll start by posting the **Resources** slice scaffolding (models/services/routes/templates) following the above, then we can iterate quickly into Customers → Sponsors.
