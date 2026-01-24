"""


## The mental model for Unit of Work (UoW)

### Wizard

* **Not a separate “function” that runs everything.**
* It’s primarily **UI flow + routing choreography**:

  * which page you’re on
  * which step comes next/back
  * what’s complete/incomplete
* Each step still ends in a **real UoW route** that commits.

Think of the wizard as “a guided sequence of UoW routes,” not an orchestrator that bypasses them.

### Routes (UoW entrypoints)

* ✅ Entry point
* ✅ Authorization gate (RBAC)
* ✅ Validate/parse inputs (typically via a Form)
* ✅ Call service(s) and possibly cross-slice contracts
* ✅ **One commit / one rollback**
* ✅ Decide response (redirect/JSON) + flash messages

### Services

* ✅ Where the business work lives (“fat”)
* ✅ Read/write using `db.session`
* ✅ Can call **their slice’s repos/models**
* ✅ May call other slices **only via contracts**
* ✅ **No commit** (but can `flush()` when needed)
* ✅ Return domain results/DTO-ish objects

### Forms

* ✅ Parse + validate request input
* ✅ Normalize to clean Python types (dates, bools, enums)
* ✅ Produce “validated payload” for the route to pass to services

### Contracts + DTOs

* ✅ The only safe cross-slice interface
* ✅ Validate inputs/outputs and raise contract-scoped errors
* ✅ DTOs are the “data envelope” crossing the boundary
* ✅ Enforce “no PII” and schema stability at the edges

### Ledger / event_bus

* `event_bus.emit(...)` is a **side-effect inside the same UoW**
* It must participate in the **same transaction**
* So Ledger append should **flush**, not commit
* The route’s final commit makes both the business facts and the audit fact durable together

---

## Summary

**Wizard = guided UX across multiple UoW routes;**
**Route = transaction boundary;**
**Service = business logic;**
**Form = input validation;**
**Contracts/DTOs = cross-slice boundary;**
**Ledger = audit side-effect inside the same commit.**



# event_bus.emit strategy/pattern
from app.extensions import event_bus

event_bus.emit(
    domain: str,                               # owning slice / domain
    operation: str,                            # what happened USE snake_case
    request_id: str,                           # request ULID
    actor_ulid: Optional[str],                 # who acted (ULID | None)
    target_ulid: Optional[str],                # primary subject | N/A
    refs: Optional[Dict[str, Any]] = None,     # small reference dictionary
    changed: Optional[Dict[str, Any]] = None,  # small “before/after” hints
    meta: Optional[Dict[str, Any]] = None,     # tiny extra context (PII-free)
    happened_at_utc: Optional[str] = None,     # ISO-8601 Z
    chain_key: Optional[str] = None,           # alternate chain (rare)
)

# CLI Checks

flask dev policy-lint --which all --base app/slices/governance/data --schema-base app/slices/governance/data/schemas
flask dev policy-health
flask dev decide-issue AC-GL-LC-L-LB-U-00B --force-blackout
flask dev issuance-debug --sku AC-GL-LC-L-LB-U-00B
flask dev issuance-tripwires --no-force-blackout --twice
flask dev demo-issue --sku AC-GL-LC-L-LB-U-00B --actor-ulid <STAFF_ULID>


Governance policy never contains table/field names for other slices.
Governance holds semantic "hints" to those tables and fields.
those hints are used to make associations and rules governing the use of
table/field data.

Semantic matching between slice-specific variables/factors and
governance policy semantic factors takes place in the target slice.

Governance only points to data with semantic hints and may provide parameters
for manipulation of that data but it never directly manipulates slice data
(read/join/write/etc.).

Refactor test:

Can I rename a column in Logistics without touching a Governance policy?
Yes = good.
No = policy/contract is leaking slice data schema into Governance policy.


Syntax:
The rules for how code must be arranged to be grammatically correct in a
language.

Semantics:
The meaning or effect of a piece of code, defining what the program is
supposed to do.

Examples of Semantic Hints in Coding:

Semantic/Meaningful Variable Names:
Using customerCount instead of x immediately tells a programmer the purpose
of the variable, even though the program would run the same way with x.

Semantic HTML:
Using tags like <header>, <nav>, <article>, and <footer> to structure a
web page. These tags provide meaning about the content they contain, which
aids accessibility tools (like screen readers) and search engines in
understanding the page's structure, whereas non-semantic <div> tags offer no
such meaning.

Type Systems:
In strongly typed languages, type declarations serve as semantic hints
that the compiler uses to ensure logical consistency and prevent type
mismatch errors.
(e.g., specifying an int vs. a float)


Governance policy schema meta example:

  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://vcdb.local/schemas/policy_fund_archetype.schema.json",
  "title": "Fund Archetype Policy Schema",
  "description": "Validates governance/data/policy_fund_archetype.json.",
  "type": "object",
  "additionalProperties": false,
  "required": ["meta", "fund_archetypes"],
  "properties": {
    "meta": {
      "type": "object",
      "additionalProperties": false,
      "required": ["title", "description", "policy_key", "version", "status", "schema_version"],
      "properties": {
        "title": { "type": "string", "minLength": 1, "pattern": "^[^\\n\\r]+$" },
        "description": { "type": "string", "minLength": 1, "pattern": "^[^\\n\\r]+$" },
        "notes": {
          "type": "array",
          "items": { "type": "string", "maxLength": 70, "pattern": "^[^\\n\\r]+$" }
        },
        "policy_key": { "type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$" },
        "version": { "type": "integer", "minimum": 1 },
        "status": { "type": "string", "enum": ["draft", "adopted", "deprecated"] },
        "effective_on": { "type": "string", "format": "date" },
        "schema_version": { "type": "integer", "minimum": 1 }
      }
    },


Governance policy meta example:

  "meta": {
    "title": "Fund Archetype Policy",
    "description": "Defines allowable fund archetypes and their restriction + payment timing semantics.",
    "notes": [
      "This policy flags revenue restrictions.",
      "In-kind is recognized as revenue/expense at fair value when recorded."
    ],
    "policy_key": "fund_archetype",
    "version": 1,
    "status": "adopted",
    "effective_on": "2025-12-01",
    "schema_version": 1
  },




"""


# a colon in set theroy represents "such that"
