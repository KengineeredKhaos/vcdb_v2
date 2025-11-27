# app/extensions/policy_hints.py

"""
Helper functions that turn policy into "hints" for humans.

Where `policy_semantics` focuses on strict correctness, this module is
aimed at surfacing advisory information: suggestions, near-misses, and
coverage hints that are useful in admin UIs or CLI diagnostics.

Current helpers:

- `hints_for_entity_type(entity_type)`:
    * Reads assignment_guidance.entity_types from policy_domain.json
      (if present) and returns any guidance strings for the given
      entity type.

- `hints_for_customer_sku_gaps()`:
    * Placeholder for future logic once Customer Profile qualifiers
      (tiers, flags, etc.) are finalized.
    * Intended to report SKUs the customer almost qualifies for.

- `hints_for_policy_coverage()`:
    * Wraps `policy_semantics.check_issuance_policy_against_catalog()`
      and presents the messages in a simple dict.

Future Dev:
- Keep this module "read-only semantics": it should not mutate policies
  or DB state. Think of it as the backing store for dashboards, reports,
  and friendly admin hints, not enforcement.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.extensions.policies import load_policy_domain


def hints_for_entity_type(entity_type: str) -> List[str]:
    """Future:
    derive domain suggestions from assignment_guidance if you add it."""
    pol = load_policy_domain()
    guidance = (pol.get("assignment_guidance") or {}).get("entity_types", {})
    return guidance.get(entity_type, [])


def hints_for_customer_sku_gaps() -> Dict[str, Any]:
    """Surface ‘near misses’—e.g.,
    SKUs the customer almost qualifies for (needs tier/vet flag)."""
    # Placeholder: you’ll wire this once Customer Profile fields finalized.
    return {"todo": "wire after Customer Profile qualifiers are settled"}


def hints_for_policy_coverage() -> Dict[str, Any]:
    """Which SKUs are active but uncovered by issuance rules?"""
    from app.extensions.policy_semantics import (
        check_issuance_policy_against_catalog,
    )

    msgs = check_issuance_policy_against_catalog()
    return {"messages": msgs}
