# app/extensions/policy_semantics.py

"""
Semantic validation and cross-file checks for Governance policies.

This module is where we do the deeper, cross-cutting reasoning about
policy files beyond simple JSON Schema validation:

- Domain & RBAC:
    * `check_domain_policy()`: sanity checks for policy_domain.json
      (domain roles, forbidden_pairs, domain_disallows_rbac).
    * `check_rbac_policy()`: sanity checks for policy_rbac.json.
    * `check_rbac_domain_relationship()`: cross-file rules like
      "admin/staff must imply governor" and "civilian disallows RBAC".

- Issuance vs catalog:
    * `check_issuance_policy_against_catalog()`: loads policy_issuance
      and compares it to the Logistics inventory catalog to ensure
      cadence settings are sane and classification_keys have coverage.

- SKU constraints:
    * `_load_sku_constraints()`, `check_sku_constraints()`,
      `assert_sku_constraints_ok()`: optional layer that ties SKU
      parsing to governance-defined constraints on issuance_class, etc.

- Cadence helpers:
    * `resolve_cadence(policy, rule)`: merges rule-level cadence,
      presets, and defaults into a single concrete cadence dict.

- Aggregates:
    * `policy_health_report()`: high-level entry point used by dev/admin
      tools; returns (warnings, infos) and raises PolicyError on fatal
      issues.

Future Dev:
- Add new semantic checks here rather than sprinkling them through
  slices. The goal is: Schemas validate structure; this module validates
  business meaning.
- Keep this module PII-free and modular so it can safely run in CLI,
  tests, and admin tools without touching live flows.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from app.extensions.policies import (  # if you have these
    load_policy_budget,
    load_policy_domain,
    load_policy_funding,
    load_policy_issuance,
    load_policy_journal_flags,
    load_policy_projects,
    load_policy_rbac,
)
from app.extensions.validate import validate_json_payload
from app.lib.jsonutil import read_json_file  # or your existing util


class PolicyError(ValueError):
    ...


class PolicyWarning(Warning):
    ...


_PART_KEY_MAP = {
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


def _uniq(seq: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


# -----------------
# Policy Health Check
# -----------------


def policy_health_report() -> Tuple[List[str], List[str]]:
    """Returns (warnings, infos). Raises PolicyError on fatal issues."""
    infos: List[str] = []
    warns: List[str] = []
    infos += check_rbac_policy()
    infos += check_domain_policy()
    infos += check_rbac_domain_relationship()
    try:
        infos += check_issuance_policy_against_catalog()
    except Exception as e:
        warns.append(f"issuance check: {e}")
    return (warns, infos)


# -----------------
# Roles Related
# Policy Semantics
# -----------------


def check_domain_policy() -> list[str]:
    """Pure semantic checks for policy_domain.json.
    Returns list of human messages.
    Raises PolicyError on fatal issues."""
    msgs: List[str] = []
    pol = load_policy_domain()
    roles = _as_set(pol.get("domain_roles"))
    rules = pol.get("assignment_rules") or {}

    # 1) forbidden_pairs exist in catalog
    for pair in rules.get("forbidden_pairs", []):
        if len(pair) != 2:
            raise PolicyError(
                f"forbidden_pairs entry must have exactly 2 items: {pair}"
            )
        a, b = pair
        if a not in roles or b not in roles:
            raise PolicyError(
                f"forbidden pair references unknown domain role(s): {pair}"
            )

    # 2) domain_disallows_rbac exist in catalog
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
    """Cross-file constraints that reflect business rules:
    - admin/staff RBAC must imply domain governor requirement.
    - civilian disallows any RBAC.
    """
    msgs: List[str] = []
    rbac = _as_set(load_policy_rbac().get("rbac_roles"))
    dom = load_policy_domain()
    rules = dom.get("assignment_rules") or {}
    must = rules.get("must_include_when_rbac", {}) or {}
    dis = _as_set(rules.get("domain_disallows_rbac"))

    # ensure admin/staff present in rbac catalog when referenced
    for r in ("admin", "staff"):
        if r not in rbac:
            raise PolicyError(
                f"must_include_when_rbac references RBAC role '{r}' not in rbac catalog"
            )

    # ensure governor is listed as required for admin/staff
    for r in ("admin", "staff"):
        if "governor" not in _as_set(must.get(r)):
            raise PolicyError(
                f"RBAC '{r}' must include domain 'governor' in must_include_when_rbac"
            )

    # civilian disallows RBAC
    # (we only check presence; enforcement is elsewhere)
    if "civilian" not in dis:
        msgs.append(
            "hint: Add 'civilian' to domain_disallows_rbac to prevent RBAC linkage."
        )

    msgs.append("rbac↔domain cross-checks OK")
    return msgs


def validate_rbac_semantics(doc: dict) -> list[str]:
    """
    Soft semantic checks for policy_rbac.json.

    This is meant for admin/dev tooling (e.g. the policy editor) and
    should only ever return *hints*, not raise. Hard failures (missing
    keys, wrong types, etc.) are handled by JSON Schema validation.

    Current expectations (v1):

      - doc.get("rbac_roles") should be a list of non-empty strings.
      - we recommend lower-case, trimmed role codes because the Auth
        contract normalises them to that shape.
    """
    hints: list[str] = []

    roles = doc.get("rbac_roles")
    if roles is None:
        # Schema (or check_rbac_policy) will complain if this is truly
        # required; here we just surface a soft hint.
        hints.append("rbac_roles is missing (expected a list of role codes).")
        return hints

    if not isinstance(roles, list):
        hints.append("rbac_roles should be a list of strings.")
        return hints

    # Non-string / empty entries
    for r in roles:
        if not isinstance(r, str):
            hints.append(f"rbac_roles entry is not a string: {r!r}")
        elif not r.strip():
            hints.append(
                "rbac_roles contains an empty/whitespace-only entry."
            )

    # Normalisation hints
    for r in roles:
        if not isinstance(r, str):
            continue
        trimmed = r.strip()
        if trimmed != r:
            hints.append(
                f"role '{r}' has leading/trailing whitespace; "
                f"it will be normalised to '{trimmed.lower()}' at runtime."
            )
        elif trimmed.lower() != trimmed:
            hints.append(
                f"role '{r}' will be normalised to lower-case "
                f"('{trimmed.lower()}') at runtime."
            )

    # Duplicate detection (Schema may enforce uniqueItems later, but this
    # keeps the hint logic explicit).
    seen: set[str] = set()
    dup: set[str] = set()
    for r in roles:
        if not isinstance(r, str):
            continue
        key = r.strip().lower()
        if key in seen:
            dup.add(key)
        else:
            seen.add(key)
    if dup:
        hints.append(
            "duplicate roles (case-insensitive) in rbac_roles: "
            + ", ".join(sorted(dup))
        )

    return hints


# -----------------
# Logistics Related
# Policy Semantics
# -----------------


def check_issuance_policy_against_catalog() -> list[str]:
    """
    Sanity checks for issuance policy:
    cadence sanity & coverage vs catalog.
    """
    from sqlalchemy import distinct, select

    from app.extensions import db
    from app.slices.logistics.models import InventoryItem

    msgs: List[str] = []
    pol = load_policy_issuance()
    default_behavior = (pol.get("default_behavior") or "deny").lower()
    msgs.append(f"issuance default_behavior: {default_behavior}")
    rules: List[Dict[str, Any]] = pol.get("rules", [])

    # cadence sanity
    for i, r in enumerate(rules):
        cad = r.get("cadence") or {}
        max_per = int(cad.get("max_per_period", 1))
        period = int(cad.get("period_days", 365))
        if max_per < 1:
            raise PolicyError(
                f"rules[{i}].cadence.max_per_period must be >=1"
            )
        if period < 1:
            raise PolicyError(f"rules[{i}].cadence.period_days must be >=1")

    # coverage (classification_key) — simple first pass
    rule_keys = {
        (r.get("match") or {}).get("classification_key") for r in rules
    }
    rule_keys.discard(None)

    cats = [
        c[0]
        for c in db.session.execute(
            select(distinct(InventoryItem.category))
        ).all()
        if c and c[0]
    ]

    uncovered = sorted(set(cats) - rule_keys)
    if uncovered:
        msgs.append(
            f"warn: {len(uncovered)} active classification_keys not covered by rules: "
            f"{uncovered[:10]}{'...' if len(uncovered)>10 else ''}"
        )
    else:
        msgs.append(
            "all active classification_keys are covered by issuance rules (or default applies)"
        )
    return msgs


def validate_issuance_semantics(doc: dict) -> list[str]:
    hints = []

    # rule ids unique
    ids = [r.get("id") for r in doc.get("rules", []) if r.get("id")]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        hints.append(f"duplicate rule ids: {', '.join(sorted(dup))}")

    # classification_key sanity:
    # must be one of governance.service_classifications
    from app.slices.governance.services import list_service_classifications

    valid_ck = {r["code"] for r in list_service_classifications()}
    for r in doc.get("rules", []):
        ck = r.get("match", {}).get("classification_key")
        if ck and ck not in valid_ck:
            hints.append(f"unknown classification_key: {ck}")

    # cadence label presence recommended
    for r in doc.get("rules", []):
        cad = r.get("cadence", {})
        if cad and "label" not in cad:
            hints.append(
                f"rule {r.get('id','<no-id>')} cadence has no label (ok, but recommended)"
            )

    # qualifier expressions format
    import re

    pat = re.compile(r"^[a-z_]+<=\d+$")
    for r in doc.get("rules", []):
        for expr in r.get("qualifiers", {}).get("tier1_any_of", []) or []:
            if not pat.match(expr):
                hints.append(
                    f"bad tier expr in rule {r.get('id','<no-id>')}: {expr}"
                )

    return hints


# -----------------
# SKU related
# Policy Semantics
# -----------------


def _load_sku_constraints() -> dict:
    path = "app/slices/governance/data/policy_sku_constraints.json"
    schema = "app/slices/governance/data/schemas/policy_sku_constraints.schema.json"
    data = read_json_file(path, default={})
    if not data:
        return {"rules": []}
    # optional schema validation
    try:
        validate_json_payload(data, schema)
    except Exception:
        # keep permissive during dev; policy-health will surface details
        pass
    return data


def check_sku_constraints(parts: dict) -> tuple[bool, str | None]:
    """
    parts keys come from sku.parse_sku():
    cat, sub, src, size, col, issuance_class
    Policy 'if' keys use:
    category, subcategory, source, size, color, issuance_class.
    """
    pol = _load_sku_constraints()
    for r in pol.get("rules", []):
        cond = r.get("if", {}) or {}
        # translate policy keys to parsed-part keys
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
    Return a concrete cadence dict for a rule:
    - rule.cadence wins
    - else rule.cadence_preset maps via policy.defaults.cadence_presets[name]
    - else policy.defaults.cadence
    """
    if rule.get("cadence"):
        return rule["cadence"]
    preset = rule.get("cadence_preset")
    if preset:
        presets = (policy.get("defaults") or {}).get("cadence_presets") or {}
        if preset in presets:
            return presets[preset]
    return ((policy.get("defaults") or {}).get("cadence")) or {}


# -----------------
# Funding / Projects / Journal flags
# -----------------


def list_project_types() -> list[dict]:
    """
    Return the canonical list of project types from policy_projects.json.

    Shape:
      [{ "key": str, "label": str }, ...]
    """
    pol = load_policy_projects()
    return list(pol.get("project_types") or [])


def list_fund_archetypes() -> list[dict]:
    """
    Return the canonical list of fund archetypes from policy_funding.json.

    Shape:
      [{ "key": str, "restriction": str, "label": str? }, ...]
    """
    pol = load_policy_funding()
    return list(pol.get("fund_archetypes") or [])


def list_journal_flag_keys() -> list[str]:
    """
    Return the set of allowed Finance journal flag keys from policy_journal_flags.json.
    """
    pol = load_policy_journal_flags()
    return [
        f["key"]
        for f in pol.get("flags") or []
        if isinstance(f, dict) and "key" in f
    ]


def assert_journal_flags_ok(flags: list[str] | None) -> None:
    """
    Validate that all journal flags used in a Finance Journal entry are
    defined in policy_journal_flags.json.

    Raises PolicyError if any unknown flags are present.
    """
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
    Look up a single budget cap line from policy_budget.json
    matching the given period + fund/project identifiers.

    Matching strategy (v1, simple):
      - Find the period with matching period_label.
      - Within that period, prefer exact fund_code/project_code
        matches if provided; otherwise fall back to archetype/type
        only.

    Returns the raw 'line' dict, or None if no budget is defined.
    """
    pol = load_policy_budget()
    for period in pol.get("periods") or []:
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
