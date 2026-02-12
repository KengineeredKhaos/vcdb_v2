# app/slices/finance/__init__.py
from __future__ import annotations

from .routes import bp

__all__ = ["bp"]
"""
======
TL;DR:
======
VCDB v2 Finance slice has four jobs:

Journal engine – low-level “post a balanced entry”:
Debits/credits, funds, projects, periods.
This is where post_journal, reverse_journal, log_donation, log_expense, etc.
live.

Funds & budgets – define “buckets” and budget envelopes:
Fund records and codes.
Transfer rules between funds/projects.
Budgets by fund/project/period.

Grants & reimbursements – this pot of money came from Sponsor X with rules Y:
Grant record.
Reimbursement lifecycle (submitted → approved → disbursed).

Reporting & projections – read-side:
Statement of Activities by period.
Balances by fund/project.
Non-monetary stats (DRMO, food pounds, etc.).

==========================================================
VCDB v2 — Finance Slice Overview & Chart of Accounts (MVP)
==========================================================

-------
Purpose
-------
The Finance slice is the system-of-record for *money as facts* in VCDB v2.
It is responsible for:

* Recording **inbound** money (donations, grants, reimbursements)
* Recording **outbound** money (expenses, reimbursements paid out)
* Maintaining a **double-entry** General Ledger (Journal + JournalLine)
* Rolling up balances by **account**, **fund**, **project**, and **period**
* Exposing read-side reports (e.g. Statement of Activities)

Finance does **not** decide policy (budgets, priorities, restrictions) and it
does **not** own projects or tasks. Those belong to:

* Governance: policy, fund archetypes, journal flags, budgets
* Calendar: projects, tasks, “who is spending for what”
* Sponsors: who gave what, and under what sponsorship program

Finance’s job is to record what *actually happened* in a clean, consistent way.

----------------------
Journal vs JournalLine
----------------------
Finance uses a two-level structure:

* ``Journal`` — the **header** for a logical financial event.
  One row per event, e.g. “$100 donation received” or “$30 program expense”.

* ``JournalLine`` — the **detail lines** for that event.
  Each line specifies:

  * ``account_code`` — *what kind of activity* (cash, revenue, expense, etc.)
  * ``fund_code`` — *which pot of money* (unrestricted, specific grant fund, etc.)
  * ``project_ulid`` — *which Calendar Project* (Stand Down 2026, Office Ops 2026, …)
  * ``amount_cents`` — integer amount in cents (positive or negative)

Every Journal entry must obey **double-entry bookkeeping**:

* Positive amounts are treated as **debits** (DR)
* Negative amounts are treated as **credits** (CR)
* For each Journal, the sum of all line amounts must be **zero**:

  ``sum(line.amount_cents for line in journal.lines) == 0``

Examples:

* Cash donation:
  * DR cash (asset up, +amount)
  * CR contributions revenue (income up, -amount)

* Program expense:
  * DR program expense (cost up, +amount)
  * CR cash (asset down, -amount)

This “zero-sum per journal” rule is enforced in the Finance services and is
central to the design of the slice.

---------------------------------------
Accounts vs Funds vs Grants vs Projects
---------------------------------------
It is important to distinguish:

* **Accounts** (Chart of Accounts)

  Describe **what kind of thing** the line represents:
  cash, receivable, revenue, expense, etc.

  These are identified by ``account_code`` (e.g. ``"1000"``, ``"4100"``,
  ``"5200"``) and live in the ``Account`` table.

* **Funds**

  Represent **pots of money** with particular restrictions:

  * Unrestricted
  * Vet-only, local-only, homeless-only
  * Specific board-designated or program-specific pots

  These are identified by ``Fund.code`` and referenced as ``fund_code`` on
  JournalLines. Governance policies (e.g. ``policy_funding.json``) define
  the allowed archetypes and restrictions; Finance enforces that the lines
  refer to valid funds.

* **Grants**

  Represent **sponsor programs** with their own rules and reporting needs:

  * Award amount and period
  * Sponsor and grant program name
  * Reimbursement vs up-front
  * Reporting cadence and required metrics

  Grants are not separate accounts; they are **labels / metadata** layered
  on top of funds and journal entries (e.g. via a Grant table and
  ``external_ref_ulid`` or flags on Journal/JournalLine).

* **Projects**

  Represent **Calendar Projects** (e.g. Stand Down 2026, Memorial Ride,
  Office Operations) which group related tasks and activities.

  JournalLines carry a ``project_ulid`` so Finance can attribute revenue
  and expenses to specific projects for later reporting and budget checks.

In short:

* Accounts answer: **“What kind of activity is this?”**
* Funds answer: **“Which pot of money is this?”**
* Grants answer: **“Under which sponsor program / paperwork blob is this?”**
* Projects answer: **“For which operational project did this happen?”**

-------------------------------------
MVP Chart of Accounts (Demonstrative)
-------------------------------------

This is a **minimal, demonstrative Chart of Accounts** for VCDB v2. It is
intended to keep things simple and to avoid “bookkeeping magic” numbers.
Future expansions can add more detail, but the *shape* should remain stable.

**Assets (1000–1999) – What we own**

* ``1000`` — Operating Cash – Checking

  Main bank account. All default donation receipts and expenses flow through
  this account.

* ``1010`` — Petty Cash  (optional)

  Small cash box used at events or for petty reimbursements.

* ``1100`` — Grants Receivable  (optional)

  Used only if the organization chooses to record grant awards as receivables
  before cash is received.

Additional asset accounts (prepaid expenses, fixed assets, etc.) can be
added later if needed.

**Liabilities (2000–2999) – What we owe**

* ``2000`` — Accounts Payable  (optional)

  Vendor bills recorded before payment (accrual basis).

* ``2200`` — Deferred Revenue / Advances  (optional)

  Money received in advance for programs not yet delivered.

For an initial cash-basis deployment, these may not be used at all.

**Net Assets (3000–3999) – What’s left over**

These represent accumulated surpluses and restrictions. They are typically
affected by year-end close processes rather than day-to-day journal entries.

* ``3100`` — Net Assets – Unrestricted
* ``3200`` — Net Assets – Temporarily Restricted
* ``3300`` — Net Assets – Permanently Restricted (endowment)
* ``3400`` — Net Assets – Board Designated (optional)

Finance does not need to write to these directly in most day-to-day flows.

**Revenue (4000–4999) – Money / value coming in**

* ``4100`` — Contributions – Cash Donations

  General cash donations from individuals or organizations. This is the
  default revenue account for ``log_donation(...)``.

* ``4200`` — Grant Revenue

  Reimbursement or grant cash from sponsors such as DOL Stand Down.

* ``4300`` — In-Kind Contributions

  Fair-value of in-kind goods (food, clothing, equipment) recorded using
  helper functions like ``record_inkind(...)``.

* ``4400`` — Event Revenue – Fundraisers  (optional)

  Ticket or registration revenue from fundraising events (e.g. Memorial Ride).

* ``4500`` — Merchandise Sales  (optional)

  Sales of hats, shirts, or similar items.

**Program Expenses (5000–5999) – Doing the mission**

* ``5100`` — Direct Client Assistance

  Gift cards, bus passes, hotel vouchers and other direct aid.

* ``5110`` — Program Supplies – Stand Down / Kits

  Supplies specifically for programs like Stand Down or Welcome Home kits.

* ``5120`` — Food & Hospitality – Programs

  Food provided at Stand Down or similar program events.

* ``5200`` — Program Supplies – General

  A general-purpose program expense account. In the current implementation,
  this is the default **expense account** for ``log_expense(...)``.

* ``5300`` — Event Costs – Memorial Ride  (optional)

  Costs directly tied to program-type events.

Initially, Finance services may post most program expenses to ``5200``,
and finer-grained codes (5110, 5120, 5300) can be introduced later as needed.

**Management & General (6000–6999) – Keeping the doors open**

* ``6100`` — Office Rent & Utilities
* ``6110`` — Office Supplies & Postage
* ``6120`` — Insurance
* ``6130`` — Professional Services (accounting, legal, tech support)

These are used when Calendar or Admin tasks log **overhead** rather than
program costs.

**Fundraising (7000–7999) – Raising money**

* ``7100`` — Fundraising Event Costs

  Overhead costs for fundraising events (venue, printing, advertising).

* ``7110`` — Donor Cultivation & Stewardship

  Donor dinners, sponsor appreciation, and similar activities.

At MVP, fundraising costs may be posted to generic expense accounts and
later migrated to specific 7000-range codes once Governance wants clearer
separation.

---------------------------
How Finance Uses This Chart
---------------------------

Service functions in the Finance slice (e.g. ``log_donation(...)``,
``log_expense(...)``) are thin, reusable “lego blocks” that:

* Choose appropriate **account_code** defaults:
  * ``1000`` for cash/bank
  * ``4100`` for cash donations
  * ``4200`` for grant revenue
  * ``5200`` for generic program expenses
* Accept explicit overrides when a more specific account is desired
* Delegate all double-entry checks and DB writes to a central
  journal engine (``post_journal(...)``)

Slices such as Sponsors, Calendar, and Governance **do not** reach into
Finance tables directly. They call Finance via contracts (e.g.
``finance_v2.log_donation``, ``finance_v2.log_expense``) using DTOs and
well-defined arguments. Finance then applies this Chart of Accounts plus
fund, grant, and project metadata to record the facts.

This keeps the mental model simple:

* **Accounts** = categories of economic activity
* **Funds** = pots of money with restrictions
* **Grants** = sponsor programs layered on funds
* **Projects** = operational efforts in Calendar that drive spending

All money in and money out becomes a *balanced* Journal entry, with a small,
canonical set of account codes that Future Devs can understand from this
docstring alone.
"""

pass
