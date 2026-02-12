# app/slices/governance/services.py
"""Governance slice — read-only policy access.

Canon: Governance Policies are JSON files under
`app/slices/governance/data/`.

- Admin-only edits are implemented in `services_admin.py` and are expected to
  be audited via the Ledger from the Admin slice.
- This module is intentionally read-only and provides a small surface for
  contracts and diagnostics.

Keep this module thin: it should not contain cross-slice business logic, and
it should not expose internal helpers intended for other slices.
"""

from __future__ import annotations

from typing import Any

from .services_admin import get_policy_impl, list_policies_impl

__all__ = [
    "load_policy_bundle",
    "svc_get_policy_value",
]


def svc_get_policy_value(family: str, key: str) -> dict[str, Any]:
    """Return a policy fragment used by contracts.

    This is a deliberately small shim to support cases where a contract wants
    a single nested object without importing the whole policy file.
    """

    family = (family or "").strip().lower()
    key = (key or "").strip().lower()

    # Current call-site: governance_v2.get_sponsor_pledge_policy
    if family == "sponsor" and key == "pledge":
        tax = get_policy_impl("policy_finance_taxonomy")
        sponsor = tax.get("sponsor", {})
        return dict(sponsor) if isinstance(sponsor, dict) else {}

    # Generic pattern: policy_<family>_<key>.json
    return get_policy_impl(f"policy_{family}_{key}")


def load_policy_bundle() -> dict[str, Any]:
    """Return a small, stable bundle used for diagnostics / describe()."""

    entity_roles = get_policy_impl("policy_entity_roles")
    operations = get_policy_impl("policy_operations")

    domain_roles = entity_roles.get("domain_roles", [])
    rbac_to_domain = entity_roles.get("assignment_rules", {}).get(
        "must_include_when_rbac", {}
    )

    projects = operations.get("projects", [])
    project_count = len(projects) if isinstance(projects, list) else 0
    projects_with_blackouts = 0
    blackout_rule_count = 0

    if isinstance(projects, list):
        for p in projects:
            rules = (p or {}).get("blackout_rules", [])
            if rules:
                projects_with_blackouts += 1
                blackout_rule_count += (
                    len(rules) if isinstance(rules, list) else 0
                )

    return {
        "domain": {
            "roles": domain_roles,
            "rbac_to_domain": rbac_to_domain,
        },
        "calendar": {
            "blackout_summary": {
                "project_count": project_count,
                "projects_with_blackouts": projects_with_blackouts,
                "blackout_rule_count": blackout_rule_count,
            }
        },
        "meta": {
            "policy_keys": list_policies_impl(),
        },
    }
