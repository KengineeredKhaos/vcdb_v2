# app/extensions/policy_semantic.py

"""
Semantic validation and cross-file checks for Governance policies
(Policy Catalog v2.0).

JSON Schema validates structure. This module validates business meaning and
cross-file invariants, without leaking slice schemas or PII.

Key checks:
- RBAC policy sanity (Auth-owned).
- Entity roles policy sanity (domain roles + assignment rules + POC).
- RBAC ↔ domain relationship constraints.
- Logistics issuance policy sanity and coverage vs Logistics catalog.
- Finance taxonomy/controls sanity (light checks only in v2; deepen later).
- Operations policy sanity (finance hint tokens reference taxonomy).

This module is safe to run in CLI/tests/admin tooling:
- PII-free outputs
- Read-only (except optional DB reads for coverage checks)
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.extensions.policies import (
    load_policy_entity_roles,
    load_policy_finance_controls,
    load_policy_finance_taxonomy,
    load_policy_logistics_issuance,
    load_policy_operations,
    load_policy_rbac,
    load_policy_service_taxonomy,
)


class PolicyError(ValueError):
    """Fatal policy problem. Treat as a hard stop for startup/admin save."""


class PolicyWarning(Warning):
    """Non-fatal policy problem. Surface in policy-health output."""


_PART_KEY_MAP = {
    # policy keys -> parsed sku part keys
    "category": "cat",
    "subcategory": "sub",
    "source": "src",
    "size": "size",
    "color": "col",
    "issuance_class": "issuance_class",
}


def _map_part_key(k: str) -> str:
    return _PART_KEY_MAP.get(k, k)


def _as_set(value: Iterable[str] | None) -> set[str]:
    return set(value or [])


def _uniq(seq: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


# -----------------
# Policy Health Check
# -----------------


def policy_health_report() -> tuple[list[str], list[str]]:
    """
    Returns (warnings, infos). Raises PolicyError on fatal issues.

    Intended to be called by CLI/admin tooling.
    """
    infos: list[str] = []
    warns: list[str] = []

    infos += check_rbac_policy()
    infos += check_entity_roles_policy()
    infos += check_rbac_domain_relationship()

    # Light finance + operations sanity checks (no DB required)
    infos += check_finance_taxonomy_policy()
    infos += check_finance_controls_policy()
    infos += check_operations_policy()

    # Logistics coverage checks may require DB; keep non-fatal here
    try:
        infos += check_logistics_issuance_policy_against_catalog()
    except Exception as e:
        warns.append(f"logistics issuance coverage: {e}")

    return (warns, infos)


# -----------------
# Roles Related Semantics
# -----------------


def _codes_from_items(
    value: Iterable[Any] | None,
    *,
    field: str = "code",
) -> set[str]:
    """
    Normalize a policy list into a set[str] of codes.

    Accepted input forms:
      - list[str]
      - list[{"code": "..."}]
    """
    out: set[str] = set()
    for item in value or []:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict) and isinstance(item.get(field), str):
            out.add(item[field])
    return out


def _domain_role_codes(pol: dict) -> set[str]:
    """Return canonical entity-domain role codes from policy."""
    return _codes_from_items(pol.get("domain_roles") or [])


def _rbac_role_codes(pol: dict) -> set[str]:
    """Return canonical RBAC role codes from policy."""
    return _codes_from_items(pol.get("rbac_roles") or [])


def _role_rule_block(
    rules: dict[str, Any],
    name: str,
    valid_roles: set[str],
) -> tuple[set[str], set[str]]:
    """
    Read a role/entity assignment rule block and validate local shape.

    Each rule block must be:
      {
        "allowed": [...],
        "default": [...]
      }

    Returns (allowed, default) as sets[str].
    """
    block = rules.get(name)
    if not isinstance(block, dict):
        raise PolicyError(
            f"assignment_rules.{name} must be an object with "
            "'allowed' and 'default' lists"
        )

    allowed = _codes_from_items(block.get("allowed") or [])
    default = _codes_from_items(block.get("default") or [])

    unknown = sorted((allowed | default) - valid_roles)
    if unknown:
        raise PolicyError(
            f"assignment_rules.{name} references unknown domain role(s): "
            f"{unknown}"
        )

    if not default.issubset(allowed):
        raise PolicyError(
            f"assignment_rules.{name}.default must be a subset of "
            f"assignment_rules.{name}.allowed"
        )

    return (allowed, default)


def check_entity_roles_policy() -> list[str]:
    """
    Pure semantic checks for policy_entity_roles.json.

    Frozen canon:
    - Domain roles are business-identity facets only.
    - Governance authority is NOT represented as a domain role.
    - EntityPerson posture roles are customer/civilian.
    - civilian may also carry resource and/or sponsor.
    - customer may not also carry resource or sponsor.
    - EntityOrg may carry only resource and/or sponsor.
    """
    msgs: list[str] = []
    pol = load_policy_entity_roles()
    roles = _domain_role_codes(pol)
    rules = pol.get("assignment_rules") or {}

    expected_roles = {
        "customer",
        "resource",
        "sponsor",
        "civilian",
    }
    if roles != expected_roles:
        raise PolicyError(
            "entity_roles.domain_roles must equal exactly "
            "['customer', 'resource', 'sponsor', 'civilian'] "
            f"(got {sorted(roles)})"
        )

    stale_keys = {
        "forbidden_pairs",
        "must_include_when_rbac",
        "domain_disallows_rbac",
    } & set(rules)
    if stale_keys:
        raise PolicyError(
            "entity_roles.assignment_rules contains obsolete key(s): "
            f"{sorted(stale_keys)}"
        )

    required_blocks = {
        "civilian",
        "customer",
        "EntityPerson",
        "EntityOrg",
        "disallow_roles",
    }
    missing_blocks = sorted(required_blocks - set(rules))
    if missing_blocks:
        raise PolicyError(
            "entity_roles.assignment_rules missing required block(s): "
            f"{missing_blocks}"
        )

    civilian_allowed, _ = _role_rule_block(rules, "civilian", roles)
    if not civilian_allowed.issubset({"resource", "sponsor"}):
        raise PolicyError(
            "assignment_rules.civilian.allowed may contain only "
            "'resource' and/or 'sponsor'"
        )

    customer_allowed, _ = _role_rule_block(rules, "customer", roles)
    if customer_allowed:
        raise PolicyError(
            "assignment_rules.customer.allowed must be empty; "
            "customer may not also be resource or sponsor"
        )

    person_allowed, _ = _role_rule_block(rules, "EntityPerson", roles)
    if person_allowed != {"customer", "civilian"}:
        raise PolicyError(
            "assignment_rules.EntityPerson.allowed must equal exactly "
            "['customer', 'civilian']"
        )

    org_allowed, _ = _role_rule_block(rules, "EntityOrg", roles)
    if not org_allowed:
        raise PolicyError(
            "assignment_rules.EntityOrg.allowed cannot be empty"
        )
    if not org_allowed.issubset({"resource", "sponsor"}):
        raise PolicyError(
            "assignment_rules.EntityOrg.allowed may contain only "
            "'resource' and/or 'sponsor'"
        )

    disallow = rules.get("disallow_roles")
    if not isinstance(disallow, dict):
        raise PolicyError("assignment_rules.disallow_roles must be an object")

    org_disallow = _codes_from_items(disallow.get("EntityOrg") or [])
    unknown_disallow = sorted(org_disallow - roles)
    if unknown_disallow:
        raise PolicyError(
            "assignment_rules.disallow_roles.EntityOrg references "
            f"unknown domain role(s): {unknown_disallow}"
        )
    if org_disallow != {"customer", "civilian"}:
        raise PolicyError(
            "assignment_rules.disallow_roles.EntityOrg must equal "
            "['customer', 'civilian']"
        )

    msgs.append(
        "entity roles OK: "
        "person posture=['customer', 'civilian']; "
        "civilian additive=['resource', 'sponsor']; "
        "org roles=['resource', 'sponsor']"
    )
    return msgs


def check_rbac_policy() -> list[str]:
    """
    Pure semantic checks for policy_rbac.json.

    RBAC policy is surface-access only. It must define role codes in the
    object-list form used by policy_rbac.json.
    """
    pol = load_policy_rbac()
    rbac_roles = _rbac_role_codes(pol)
    if not rbac_roles:
        raise PolicyError("rbac_roles list cannot be empty")

    required_minimum = {"user", "auditor", "staff", "admin"}
    missing = sorted(required_minimum - rbac_roles)
    if missing:
        raise PolicyError(
            "rbac_roles missing required code(s): " f"{missing}"
        )

    return [f"rbac roles: {sorted(rbac_roles)}"]


def check_rbac_domain_relationship() -> list[str]:
    """
    Cross-file separation checks:

    - RBAC roles define surface access only.
    - Domain roles define business identity facets only.
    - Governance business authority is assigned through Governance
      office/pro tem records, not domain roles.
    """
    msgs: list[str] = []
    rbac = _rbac_role_codes(load_policy_rbac())
    dom = load_policy_entity_roles()
    rules = dom.get("assignment_rules") or {}
    overlap = sorted(rbac & roles)
    if overlap:
        raise PolicyError(
            "RBAC role codes and domain role codes must be distinct; "
            f"overlap found: {overlap}"
        )

    forbidden_domain_roles = {"governor", "staff"} & roles
    if forbidden_domain_roles:
        raise PolicyError(
            "entity_roles.domain_roles contains stale authority/access "
            f"role(s): {sorted(forbidden_domain_roles)}"
        )

    stale_keys = {
        "must_include_when_rbac",
        "domain_disallows_rbac",
    } & set(rules)
    if stale_keys:
        raise PolicyError(
            "entity_roles.assignment_rules contains obsolete RBAC-coupling "
            f"key(s): {sorted(stale_keys)}"
        )

    msgs.append(
        "rbac↔domain separation OK: "
        "RBAC=surface access, domain=business identity, "
        "governance authority lives outside entity roles"
    )
    return msgs


# -----------------
# Finance + Operations sanity
# -----------------


def check_finance_taxonomy_policy() -> list[str]:
    pol = load_policy_finance_taxonomy()
    msgs: list[str] = []

    fund_keys = pol.get("fund_keys") or {}
    restriction_keys = pol.get("restriction_keys") or {}
    income_kinds = pol.get("income_kinds") or {}
    expense_kinds = pol.get("expense_kinds") or {}
    spending_classes = pol.get("spending_classes") or {}

    if not isinstance(fund_keys, dict) or not fund_keys:
        raise PolicyError(
            "finance_taxonomy.fund_keys must be a non-empty object"
        )

    if not isinstance(restriction_keys, dict) or not restriction_keys:
        raise PolicyError(
            "finance_taxonomy.restriction_keys must be a non-empty object"
        )

    if not isinstance(income_kinds, dict) or not income_kinds:
        raise PolicyError(
            "finance_taxonomy.income_kinds must be a non-empty object"
        )

    if not isinstance(expense_kinds, dict) or not expense_kinds:
        raise PolicyError(
            "finance_taxonomy.expense_kinds must be a non-empty object"
        )

    if not isinstance(spending_classes, dict) or not spending_classes:
        raise PolicyError(
            "finance_taxonomy.spending_classes must be a non-empty object"
        )

    msgs.append(
        "finance taxonomy: "
        f"fund_keys={len(fund_keys)} "
        f"restriction_keys={len(restriction_keys)} "
        f"income_kinds={len(income_kinds)} "
        f"expense_kinds={len(expense_kinds)} "
        f"spending_classes={len(spending_classes)}"
    )
    return msgs


def check_finance_controls_policy() -> list[str]:
    pol = load_policy_finance_controls()
    msgs: list[str] = []

    spending = pol.get("spending") or {}
    staff_cap = spending.get("staff_cap_cents")
    if staff_cap is None:
        raise PolicyError(
            "finance_controls.spending.staff_cap_cents is required"
        )
    try:
        staff_cap_int = int(staff_cap)
    except Exception as e:
        raise PolicyError(
            f"finance_controls.spending.staff_cap_cents must be an int: {e}"
        ) from e
    if staff_cap_int < 0:
        raise PolicyError(
            "finance_controls.spending.staff_cap_cents must be >= 0"
        )

    budget = pol.get("budget") or {}
    periods = budget.get("periods") or []
    if not isinstance(periods, list):
        raise PolicyError("finance_controls.budget.periods must be a list")

    msgs.append(
        f"finance controls: staff_cap_cents={staff_cap_int} budget_periods={len(periods)}"
    )
    return msgs


def _expense_kind_keys() -> set[str]:
    pol = load_policy_finance_taxonomy()
    ek = pol.get("expense_kinds") or {}

    if not isinstance(ek, dict):
        return set()

    return {str(k) for k in ek.keys() if str(k).strip()}


def check_operations_policy() -> list[str]:
    pol = load_policy_operations()
    msgs: list[str] = []

    task_kinds = pol.get("task_kinds") or []
    if not isinstance(task_kinds, list) or not task_kinds:
        raise PolicyError("operations.task_kinds must be a non-empty list")

    valid_expense_kinds = _expense_kind_keys()
    if not valid_expense_kinds:
        msgs.append(
            "hint: finance_taxonomy.expense_kinds is empty; cannot validate operations.finance_hints.expense_kinds"
        )

    bad_refs: list[str] = []
    for tk in task_kinds:
        if not isinstance(tk, dict):
            continue
        fh = tk.get("finance_hints") or {}
        exp = fh.get("expense_kinds") or []
        if not valid_expense_kinds:
            continue
        for k in exp:
            if k not in valid_expense_kinds:
                bad_refs.append(f"{tk.get('key', '<no-key>')} -> {k}")

    if bad_refs:
        raise PolicyError(
            "operations task_kinds reference unknown expense_kinds: "
            + ", ".join(bad_refs[:10])
        )

    msgs.append(
        f"operations: task_kinds={len(task_kinds)} projects={len((pol.get('projects') or {}).keys())}"
    )
    return msgs


# -----------------
# Logistics: issuance vs catalog + SKU constraints
# -----------------


def _cadence_sanity(cad: dict, *, where: str) -> None:
    try:
        max_per = int(cad.get("max_per_period", 1))
        period = int(cad.get("period_days", 365))
    except Exception as e:
        raise PolicyError(f"{where}: cadence fields must be ints: {e}") from e
    if max_per < 1:
        raise PolicyError(f"{where}: cadence.max_per_period must be >= 1")
    if period < 1:
        raise PolicyError(f"{where}: cadence.period_days must be >= 1")


def check_logistics_issuance_policy_against_catalog() -> list[str]:
    """
    Sanity checks for logistics_issuance:
    - cadence sanity (defaults + any rule cadence)
    - coverage (classification_key) vs Logistics inventory catalog
    """
    from sqlalchemy import distinct, select

    from app.extensions import db
    from app.slices.logistics.models import InventoryItem

    msgs: list[str] = []
    pol = load_policy_logistics_issuance()

    issuance = pol.get("issuance") or {}
    defaults = issuance.get("defaults") or {}
    default_cad = defaults.get("cadence") or {}
    if default_cad:
        _cadence_sanity(default_cad, where="issuance.defaults.cadence")

    sku_constraints = pol.get("sku_constraints") or {}
    rules: list[dict[str, Any]] = list(sku_constraints.get("rules") or [])

    for i, r in enumerate(rules):
        cad = r.get("cadence") or {}
        if cad:
            _cadence_sanity(cad, where=f"sku_constraints.rules[{i}].cadence")

    rule_keys = {
        (r.get("match") or {}).get("classification_key") for r in rules
    }
    rule_keys.discard(None)

    attr = (
        getattr(InventoryItem, "classification_key", None)
        or InventoryItem.category
    )
    cats = [
        c[0]
        for c in db.session.execute(select(distinct(attr))).all()
        if c and c[0]
    ]

    uncovered = sorted(set(cats) - rule_keys)
    if uncovered:
        msgs.append(
            f"warn: {len(uncovered)} active classification keys not covered by cadence rules: "
            f"{uncovered[:10]}{'...' if len(uncovered) > 10 else ''}"
        )
    else:
        msgs.append(
            "all active classification keys are covered by cadence rules (or default applies)"
        )

    return msgs


def _service_classification_codes() -> set[str]:
    """
    Return known classification codes from service_taxonomy policy.
    """
    pol = load_policy_service_taxonomy()
    cls = pol.get("classifications") or {}
    if isinstance(cls, dict) and isinstance(cls.get("map"), dict):
        return set(cls["map"].keys())
    if isinstance(cls, dict):
        return {k for k in cls.keys() if "/" in k or "." in k or k.isupper()}
    return set()


def validate_issuance_semantics(doc: dict) -> list[str]:
    """
    Soft semantic checks for logistics_issuance policy payload.

    Returns hints only; hard failures are handled elsewhere.
    """
    hints: list[str] = []
    sku_constraints = doc.get("sku_constraints") or {}
    rules = sku_constraints.get("rules") or []
    if not isinstance(rules, list):
        return ["sku_constraints.rules should be a list"]

    valid_ck = _service_classification_codes()
    if valid_ck:
        for r in rules:
            if not isinstance(r, dict):
                continue
            ck = (r.get("match") or {}).get("classification_key")
            if ck and ck not in valid_ck:
                hints.append(
                    f"unknown classification_key in cadence rule: {ck}"
                )
    else:
        hints.append(
            "hint: service_taxonomy classifications not available; cannot validate classification_key references"
        )

    return hints


def _issuance_rules_for_sku_constraints() -> list[dict]:
    """Rules that constrain SKU issuance_class based on SKU parts."""
    pol = load_policy_logistics_issuance()
    issuance = pol.get("issuance") or {}
    return list(issuance.get("rules") or [])


def check_sku_constraints(parts: dict) -> tuple[bool, str | None]:
    """
    Enforce issuance_class constraints based on SKU parts.
    """
    for r in _issuance_rules_for_sku_constraints():
        cond = r.get("if", {}) or {}
        if all(parts.get(_map_part_key(k)) == v for k, v in cond.items()):
            expected = (r.get("then") or {}).get("issuance_class")
            if expected and parts.get("issuance_class") != expected:
                why = r.get("why") or f"requires issuance_class={expected}"
                return (False, why)
    return (True, None)


def assert_sku_constraints_ok(parts: dict) -> None:
    ok, why = check_sku_constraints(parts)
    if not ok:
        raise ValueError(f"SKU violates constraints: {why}")


def resolve_cadence(policy: dict, rule: dict) -> dict:
    """
    Return a concrete cadence dict for a cadence-bearing rule in logistics_issuance.
    """
    if rule.get("cadence"):
        return rule["cadence"]
    preset = rule.get("cadence_preset")
    if preset:
        presets = ((policy.get("issuance") or {}).get("defaults") or {}).get(
            "cadence_presets"
        ) or {}
        if preset in presets:
            return presets[preset]
    return (
        ((policy.get("issuance") or {}).get("defaults") or {}).get("cadence")
    ) or {}


# -----------------
# Finance helper accessors (v2)
# -----------------


def list_fund_archetypes() -> list[dict]:
    """
    Legacy alias.

    The old finance taxonomy exposed fund_archetypes as a list.
    The new taxonomy exposes fund_keys as an object keyed by fund key.

    Return a normalized list of dicts so older callers can survive
    during migration.
    """
    pol = load_policy_finance_taxonomy()
    fund_keys = pol.get("fund_keys") or {}

    if not isinstance(fund_keys, dict):
        return []

    out: list[dict] = []
    for key, spec in fund_keys.items():
        spec = spec or {}
        out.append(
            {
                "key": str(key),
                "label": str(spec.get("label") or key),
                "archetype": spec.get("archetype"),
                "default_restriction_keys": list(
                    spec.get("default_restriction_keys") or []
                ),
            }
        )
    out.sort(key=lambda x: str(x["key"]))
    return out


def list_journal_flag_keys() -> list[str]:
    """
    Legacy helper.

    journal_flags are not part of the new finance taxonomy model.
    Return an empty list until/unless they are reintroduced under a
    dedicated policy surface.
    """
    return []


def assert_journal_flags_ok(flags: list[str] | None) -> None:
    if not flags:
        return
    allowed = set(list_journal_flag_keys())
    unknown = sorted(set(flags) - allowed)
    if unknown:
        raise PolicyError(f"Unknown journal flag(s): {unknown}")


def find_budget_cap(
    *,
    period_label: str,
    fund_archetype_key: str,
    project_type_key: str,
    fund_code: str | None = None,
    project_code: str | None = None,
) -> dict | None:
    """
    Look up a single budget cap line from finance_controls.
    """
    pol = load_policy_finance_controls()
    periods = ((pol.get("budget") or {}).get("periods")) or []
    for period in periods:
        if period.get("period_label") != period_label:
            continue
        for line in period.get("lines") or []:
            if line.get("status") != "adopted":
                continue

            if line.get("fund_archetype_key") != fund_archetype_key:
                continue
            if line.get("project_type_key") != project_type_key:
                continue

            if fund_code and line.get("fund_code") not in (None, fund_code):
                continue
            if project_code and line.get("project_code") not in (
                None,
                project_code,
            ):
                continue

            return line
    return None


# -----------------
# Legacy aliases (temporary)
# -----------------
# Keep old function names alive while the rest of the app is refactored.
# Delete these once all call sites are migrated.

check_domain_policy = check_entity_roles_policy
check_issuance_policy_against_catalog = (
    check_logistics_issuance_policy_against_catalog
)
