# Home Page / Navbar UX Brief

This is the current design brief for the app root landing page and top navbar.

### Purpose

The top navbar should be **global app chrome**, not the primary operator workflow switchboard. The landing page should be the **operator dispatch surface** for daily work.

That direction fits the current system better than the existing slice-heavy nav in `base.html`, which is trying to carry both global reference links and workflow entry points at the same time.

---

## 1. Navbar intent

The navbar is for things that are global, stable, and cross-app.

### Navbar contents

**Visible to everyone**

- Brand / Home (`VCDB`)

- `Public Info` dropdown
  
  - statutorily required public documents
  
  - Articles of Incorporation
  
  - Bylaws
  
  - financial statements
  
  - other public-facing organizational documents

**Visible to authenticated operators only**

- `User Docs` dropdown
  
  - runbooks
  
  - operator quick-reference material
  
  - internal procedural docs

**Visible to admins only**

- `Admin Dashboard`

**Right side**

- operator identity / account area
  
  - logged-in operator name
  
  - change password
  
  - logout

This aligns with the auth slice, which already exposes login, logout, change-password, and admin-only auth surfaces.  
It also corrects the current base template behavior, which redundantly renders operator identity in the header.

### Navbar non-goals

The navbar should **not** be the main place for:

- Customers

- Resources

- Sponsors

- intake or onboarding starts

- entity creation tasks

Those belong on the landing page hero cards.

---

## 2. Home page intent

The home page is the **operator workbench**.

It should answer:

- What kind of work are you doing?

- Are you opening existing work or starting new work?

- Is there anything you need to notice before proceeding?

It should **not** pretend to be a generic one-click resume surface.

---

## 3. Why there is no generic “Resume” button

Workflow resumption in the current app is **entity-specific**, not operator-global.

Customer intake resumes only after the system knows which `entity_ulid` is being worked on. The resume entry point is tied to a specific customer entity, and the next step is derived from that record’s saved state.

The Entity wizard, Resource onboarding, and Sponsor onboarding each also track active work in a session-scoped, flow-specific way. That makes them resumable only when the target person or organization is known.

Because operators may have multiple interrupted flows for different people or organizations, a generic Home-page `Resume` button would be ambiguous and misleading.

### Rule

Home starts a **class of work**.  
List/search/open pages identify the **specific record**.  
The wizard then resumes the **correct next step** for that record.

---

## 4. Brand/Home behavior

The `VCDB` brand button should continue to return to Home.

That is the correct “bail out” behavior.

Why this is acceptable:

- the flows are already designed to tolerate interruption

- stale submits are handled explicitly

- saved progress can be resumed later once the operator re-selects the correct record

Caveat: unsaved data on the current page may still be lost. That is acceptable and honest.

---

## 5. Hero card pattern

All hero cards should follow the same structure.

### Standard card shape

- one short plain-English title

- one short muted description

- one primary **open existing** action

- one primary **start new** action

- one smaller secondary action if needed

This uniformity is intentional. Predictability helps infrequent operators and makes unusual banners or advisories more noticeable.

---

## 6. Hero cards to include

### Customers

**Purpose:** person-served workflow

**Primary actions**

- `Find / Open Customer`

- `Start Customer Intake`

**Why:** the Customer slice is a true operator work lane: list, overview, intake, provider matching, referrals, outcomes, and history.

**Note:** “Start Customer Intake” is more honest than “Create New Customer,” because creation begins through the Entity wizard and then hands off into Customer intake.

---

### Resources

**Purpose:** provider / organization workflow

**Primary actions**

- `Search / Open Resources`

- `Onboard Resource Org`

**Secondary action**

- `Add Resource Contact`

**Why:** Resource onboarding is a real multi-step operator workflow and includes POC/contact handling as part of the resource lane.

---

### Sponsors

**Purpose:** donor / sponsoring organization workflow

**Primary actions**

- `Search / Open Sponsors`

- `Onboard Sponsor Org`

**Secondary action**

- `Add Sponsor Contact`

**Why:** Sponsor onboarding is also a real multi-step operator workflow and includes POC/contact handling inside the sponsor lane.

---

## 7. Contact / POC design rule

`Contact` is the preferred operator-facing term.  
`POC` may remain internal shorthand.

A separate Contact hero card is **not** recommended at this time.

Reason:

- contact work is not a separate peer business lane

- contact creation/linking is subordinate to Resource and Sponsor workflows

- a dedicated card would force operators to think about implementation instead of task intent

The actual system flow supports this interpretation:

- a person may be created or selected first

- then linked as a Resource or Sponsor contact

- the Entity wizard already supports handoff to Resource POC or Sponsor POC linking for a person with no other stream role

- the raw attach routes for Resource and Sponsor contacts require a known person ULID, which confirms that contact work is really a person-first linking flow under the hood

### Important UI rule

`Add Resource Contact` and `Add Sponsor Contact` are acceptable operator labels even though the implementation may pass through shared person/entity creation logic first. The operator-facing label should describe the **intent and result**, not the internal mechanics.

---

## 8. Home page support elements

### Operator status strip

Add a small status strip near the top of Home showing:

- who is logged in on this browser/kiosk

- optionally RBAC role or comparable operator status

Purpose:

- supervisors can tell at a glance which operator is active on a station

- reinforces session accountability

- fits shared-kiosk operation

This builds naturally on the existing authenticated user display logic in the base template and auth flow.

### Attention-needed banner area

Reserve a small area on Home for future advisory/attention messages.

Examples:

- policy update notices

- operator status changes

- governor / officer / pro tem assignment or removal

- other important admin advisories

This infrastructure is not fully in place yet, but the concept is valid and consistent with the system’s existing admin/advisory direction. Customer flow already publishes some admin advisory items in certain cases.

This area should stay modest and noticeable, not become a giant dashboard.

---

## 9. Tone and wording guidance

Use:

- short labels

- verb-first buttons

- muted helper text

- plain English

Good examples:

- `Find / Open Customer`

- `Start Customer Intake`

- `Search / Open Resources`

- `Onboard Resource Org`

- `Add Resource Contact`

Avoid:

- overly technical language

- internal schema vocabulary

- labels that imply system behavior that is not actually true

- cluttered dashboard language

Muted helper text is intentional. It supports infrequent operators without turning the page into a wall of text.

---

## 10. Summary decision log

### Accepted

- Navbar becomes global chrome, not workflow routing

- Public Info visible to everyone

- User Docs visible only to authenticated operators

- Admin Dashboard rendered only for admins

- operator identity/account controls shown in header

- Home page becomes operator dispatch surface

- no generic Resume button

- hero cards use uniform layout

- Resource and Sponsor cards include contact actions

- no separate Contact hero card

- operator status strip is desirable

- future attention-needed banner area is desirable

### Rejected

- slice-heavy workflow navbar

- generic Home-page Resume button

- separate Contact Creation hero card

- exposing too many app-internal concepts at top level

---

## 11. Working principle for Future Dev

**Header is global.**  
**Home starts work lanes.**  
**Lists/search select records.**  
**Wizards resume entity-specific progress.**


