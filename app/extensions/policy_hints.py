"""
Helper functions that turn Governance policy into "hints" for humans.

Where `policy_semantics` focuses on correctness (fatal errors and strong
guarantees), this module is advisory: suggestions, near-misses, and
coverage hints that are useful in admin UIs or CLI diagnostics.

Rules:
- Read-only: never mutate policies or DB state.
- PII-free: all outputs must be safe for logs/CLI.

Policy Catalog v2.0 notes:
- Domain/POC hints now come from `policy_entity_roles.json`
  (policy_key: "entity_roles").
- Issuance coverage hints now come from `policy_logistics_issuance.json`
  (policy_key: "logistics_issuance").
"""

from __future__ import annotations

from typing import Any

from app.extensions.policies import load_policy_entity_roles


def hints_for_entity_type(entity_type: str) -> list[str]:
    """
    Return advisory guidance strings for an entity type, if present.

    This is intentionally optional: if you do not define
    entity_roles.assignment_guidance, the function returns [].
    """
    pol = load_policy_entity_roles()
    guidance = (pol.get("assignment_guidance") or {}).get("entity_types", {})
    return list(guidance.get(entity_type, []) or [])


def hints_for_customer_sku_gaps() -> dict[str, Any]:
    """
    Placeholder: surface ‘near misses’—e.g. SKUs the customer almost
    qualifies for (needs tier/vet flag).
    """
    return {"todo": "wire after Customer Profile qualifiers are settled"}


def hints_for_policy_coverage() -> dict[str, Any]:
    """Which catalog classifications are uncovered by issuance cadence rules?"""
    from app.extensions.policy_semantics import (
        check_logistics_issuance_policy_against_catalog,
    )

    msgs = check_logistics_issuance_policy_against_catalog()
    return {"messages": msgs}
