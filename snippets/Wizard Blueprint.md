# Wizard Blueprint

## The right mental model for a wizard

A wizard is **multiple UoWs**, not one giant UoW.

Each step is its own entrypoint with:

* clear inputs
* clear writes
* one commit/rollback
* a resumable state

The “wizard” UX is just the front-end choreography on top of those UoWs.

---

## Wizard architecture that works well in your app

### Step 0 — Start intake (creates the *anchor*)

**UoW:** `POST /customers/intake/start`
**Goal:** create the minimal durable identity so everything else can attach to it.

**Writes**

* Entity (person) + minimal PersonPII (first/last)
* Customer row (links to entity)
* CustomerEligibility row (defaults)
* `customer.intake.started` ledger event

**Return**

* `customer_ulid`, `entity_ulid`
* redirect to Step 1

**Why this step matters**
It creates a stable ULID anchor so:

* tabs can load data immediately
* later steps can be saved independently
* staff can stop midway and resume

### Step 0 route

`GET /customers/intake/lookup` (blank form)

`POST /customers/intake/lookup` (run search, show results)

#### Inputs (minimal):
- first_name
- last_name
- dob (high value)
- last4 (optional but high value)

#### Output:

- `0 matches` → show “Create new customer” button → goes to POST /customers/intake/start
- `1+ matches` → show “Possible matches” list:
- Open existing customer/entity
- Go to merge workflow (Identity slice)
- “Create new anyway” (requires reason + logs customer.intake.override_duplicate_check)

### Step 1 — Identity (PII core)

**UoW:** `POST /customers/<customer_ulid>/intake/identity`
Inputs: preferred name, DOB, last4
Writes: Entity slice PII fields
Event: `domain="customer" operation="personal_updated"`

### Step 2 — Veteran qualification

**UoW:** `POST /customers/<customer_ulid>/intake/eligibility/veteran`
Inputs: veteran_method + verified flag
Writes: Customers slice eligibility
Event: `domain="customer", operation="eligibility_updated"`

(If you want homeless, make it a separate step too—don’t overload.)

### Step 3 — Contact points

**UoW:** `POST /customers/<customer_ulid>/intake/contact`
Inputs: phone/email
Writes: Entity contactpoints
Event: `customer.contact.updated`

### Step 4 — Address

**UoW:** `POST /customers/<customer_ulid>/intake/address`
Inputs: street/city/state/zip
Writes: Entity address
Event: `customer.contact.updated` (or separate `customer.address.updated` if you want)

### Step 5 — Review + finalize

**UoW:** `POST /customers/<customer_ulid>/intake/complete`
Goal: mark intake status complete (or “active”)
Writes: Customers slice status column (if you have one; if not, add it)
Event: `customer.intake.completed`

---

## Tabs + wizard can coexist cleanly

* Wizard controls *how you gather the data*
* Tabs control *how you display it once it exists*

This works best if Step 0 creates the Customer early, so the “Customer Detail” page can immediately render tabs:

**Customer Detail tabs (read-only until completed, or partially editable):**

* Overview
* Identity
* Eligibility
* Contact
* Address
* Ledger Activity (read-only)

---

## What about “flush vs commit” here?

In this wizard design:

* **each step commits** (by design)
* you do **not** need explicit flushes in most steps
* each step is small enough to be reliable and testable

This is exactly how you avoid one huge cross-slice transaction that’s hard to reason about.

---

## The testing plan that matches this

For each wizard step:

* **Route test (happy path)**: POST → 302 redirect → DB contains expected changes → ledger event exists
* **Route test (red path)**: missing required field → 200 with form errors (or 400 JSON) → DB unchanged

That gives you a stable “UI simulator” test suite.

---

## One key design decision to make now

Do you want Step 0 to create:

1. **Customer + Entity minimal** (recommended), or
2. a separate **IntakeDraft** row that later becomes a customer?

Given your ethos (“nothing happens in the dark”, no deletes, and you want stable ULIDs), option **1** is cleaner: create the real Customer early and mark it “intake_incomplete”.

---

If you want, your next move can be simple:

1. You write the UoW specs for just **Step 0 + Step 1** in your outline format.
2. I’ll turn that into:

   * route signatures
   * form field lists
   * RBAC decorators
   * and the first two route tests

Then we iterate step-by-step until the whole wizard is nailed down.

---

## Unit of Work Descriptions

- Slice / UoW name
- Route: METHOD /path
- Who can do it: (staff/admin/auditor + any governor requirement)
- Inputs: fields
- Does: 3–6 bullet steps
- Writes: list entities affected (high-level)
- Emits: domain.operation
- Returns: where it redirects or JSON response
- Failure modes: 1–3 common ones

