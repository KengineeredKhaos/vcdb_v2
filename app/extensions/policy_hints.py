# app/extensions/policy_hints.py
from __future__ import annotations

from typing import Any, Dict, List

from app.extensions.contracts.catalog_v2 import list_skus
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
