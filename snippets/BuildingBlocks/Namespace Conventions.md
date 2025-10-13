# Namespace Conventions

Pythonic cheat-sheet (PEP 8-aligned) for naming “levels”:

## TL;DR

If you stick to:

- files & funcs = `snake_case`
- classes/exceptions = `CamelCase`
- constants/env = `UPPER_SNAKE_CASE`

…you’ll be right in line with PEP 8 and most linters.

## Files & modules

* **Packages / module files / directories:** `snake_case`
  
  * e.g. `app/extensions/contracts`, `governance_v1.py`

## Code identifiers

* **Functions & variables (including module-level):** `snake_case`
  
  * `load_policy()`, `allowed_roles`, `to_iso8601`

* **Methods & attributes:** `snake_case`
  
  * `def emit_event(self, payload):`

* **Classes & Exceptions:** **CapWords** (aka **CamelCase** / **PascalCase**)
  
  * `class PolicyService:`, `class PolicyValidationError(Exception):`

* **Constants:** **UPPER_SNAKE_CASE**
  
  * `DEFAULT_ROLES`, `ERA_DEFAULT`, `RFC3339_PATTERN`

* **Type aliases / Protocols / Enums:** CapWords
  
  * `type PolicyDTO = dict[str, Any]`, `class Domain(Enum): ...`

* **“Private” (non-public):** prefix with a single underscore
  
  * `_validate_roles()`, `_internal_cache`

* **Magic / dunder names:** reserved by Python
  
  * `__init__`, `__all__`, `__repr__`

## Not typically used in Python

* **lowerCamelCase:** generally avoid (Java/JS style)

## Extras you’ll likely use

* **Environment variables:** `UPPER_SNAKE_CASE` (e.g., `DATABASE_URL`)
* **JSON keys / API fields:** pick a consistent style; in Python projects,
  `snake_case` is common, but if a public API already uses `camelCase`,
  keep it consistent at the boundary and map to snake_case internally.
