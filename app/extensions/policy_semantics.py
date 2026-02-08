"""
Semantic validation and cross-file checks for Governance policies (Policy Catalog v2.0).

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


def _domain_role_codes(pol: dict) -> set[str]:
    """
    Domain roles may be represented as:
      - list[str]
      - list[{"code": "..."}]
    Return a set[str] of codes.
    """
    raw = pol.get("domain_roles") or []
    out: set[str] = set()
    for r in raw:
        if isinstance(r, str):
            out.add(r)
        elif isinstance(r, dict) and isinstance(r.get("code"), str):
            out.add(r["code"])
    return out


def check_entity_roles_policy() -> list[str]:
    """
    Pure semantic checks for policy_entity_roles.json.

    Returns list of human messages.
    Raises PolicyError on fatal issues.
    """
    msgs: list[str] = []
    pol = load_policy_entity_roles()
    roles = _domain_role_codes(pol)
    rules = pol.get("assignment_rules") or {}

    if not roles:
        raise PolicyError("entity_roles.domain_roles cannot be empty")

    # forbidden_pairs exist in catalog
    for pair in rules.get("forbidden_pairs", []):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise PolicyError(
                f"forbidden_pairs entry must have exactly 2 items: {pair!r}"
            )
        a, b = pair
        if a not in roles or b not in roles:
            raise PolicyError(
                f"forbidden_pairs references unknown domain role(s): {pair!r}"
            )

    # domain_disallows_rbac exist in catalog
    dis = _as_set(rules.get("domain_disallows_rbac"))
    missing = [r for r in dis if r not in roles]
    if missing:
        raise PolicyError(
            f"domain_disallows_rbac references unknown roles: {missing}"
        )

    msgs.append(f"domain roles: {len(roles)}; disallows_rbac: {sorted(dis)}")
    return msgs


def check_rbac_policy() -> list[str]:
    pol = load_policy_rbac()
    rbac_roles = _as_set(pol.get("rbac_roles"))
    if not rbac_roles:
        raise PolicyError("rbac_roles list cannot be empty")
    return [f"rbac roles: {sorted(rbac_roles)}"]


def check_rbac_domain_relationship() -> list[str]:
    """
    Cross-file constraints that reflect business rules:
    - admin/staff RBAC must imply domain governor requirement.
    - civilian disallows any RBAC (recommended hint if missing).
    """
    msgs: list[str] = []
    rbac = _as_set(load_policy_rbac().get("rbac_roles"))
    dom = load_policy_entity_roles()
    rules = dom.get("assignment_rules") or {}
    must = rules.get("must_include_when_rbac", {}) or {}
    dis = _as_set(rules.get("domain_disallows_rbac"))
    roles = _domain_role_codes(dom)

    # ensure admin/staff present in rbac catalog when referenced
    for r in ("admin", "staff"):
        if r not in rbac:
            raise PolicyError(
                f"must_include_when_rbac references RBAC role '{r}' not in rbac catalog"
            )

    # ensure governor is listed as required for admin/staff
    for r in ("admin", "staff"):
        req = _as_set(must.get(r))
        if "governor" not in req:
            raise PolicyError(
                f"RBAC '{r}' must include domain 'governor' in must_include_when_rbac"
            )
        if "governor" not in roles:
            raise PolicyError(
                "entity_roles.domain_roles must include 'governor'"
            )

    # civilian disallows RBAC (soft hint)
    if "civilian" in roles and "civilian" not in dis:
        msgs.append(
            "hint: Add 'civilian' to domain_disallows_rbac to prevent RBAC linkage."
        )

    msgs.append("rbac↔domain cross-checks OK")
    return msgs


# -----------------
# Finance + Operations sanity
# -----------------


def check_finance_taxonomy_policy() -> list[str]:
    pol = load_policy_finance_taxonomy()
    msgs: list[str] = []

    fa = pol.get("fund_archetypes") or []
    if not isinstance(fa, list) or not fa:
        raise PolicyError(
            "finance_taxonomy.fund_archetypes must be a non-empty list"
        )

    jf = pol.get("journal_flags") or []
    if not isinstance(jf, list):
        raise PolicyError("finance_taxonomy.journal_flags must be a list")

    ek = pol.get("expense_kinds") or []
    if ek and not isinstance(ek, list):
        raise PolicyError(
            "finance_taxonomy.expense_kinds must be a list when present"
        )

    msgs.append(
        f"finance taxonomy: fund_archetypes={len(fa)} journal_flags={len(jf)} expense_kinds={len(ek)}"
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
        )
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
    ek = pol.get("expense_kinds") or []
    out: set[str] = set()
    for item in ek:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict) and isinstance(item.get("key"), str):
            out.add(item["key"])
    return out


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
        raise PolicyError(f"{where}: cadence fields must be ints: {e}")
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
    pol = load_policy_finance_taxonomy()
    return list(pol.get("fund_archetypes") or [])


def list_journal_flag_keys() -> list[str]:
    pol = load_policy_finance_taxonomy()
    flags = pol.get("journal_flags") or []
    out: list[str] = []
    for f in flags:
        if isinstance(f, str):
            out.append(f)
        elif isinstance(f, dict) and isinstance(f.get("key"), str):
            out.append(f["key"])
    return _uniq(out)


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
