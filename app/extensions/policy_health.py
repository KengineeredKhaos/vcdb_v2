# app/extensions/policy_health.py

from __future__ import annotations

from typing import Any

from app.extensions.policies import load_governance_policy
from app.extensions.policies import load_policy_finance_taxonomy
from app.extensions.policies import load_policy_funding_decisions


class PolicyError(RuntimeError):
    """Fatal governance policy health error."""


def _as_key_set(obj: object) -> set[str]:
    if not isinstance(obj, dict):
        return set()
    return {str(k).strip() for k in obj.keys() if str(k).strip()}


def _as_list_of_str(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        s = str(v).strip()
        if s:
            out.append(s)
    return out


def _check_finance_taxonomy() -> tuple[list[str], list[str]]:
    infos: list[str] = []
    warns: list[str] = []

    pol = load_policy_finance_taxonomy()

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

    infos.append(
        "finance taxonomy: "
        f"fund_keys={len(fund_keys)} "
        f"restriction_keys={len(restriction_keys)} "
        f"income_kinds={len(income_kinds)} "
        f"expense_kinds={len(expense_kinds)} "
        f"spending_classes={len(spending_classes)}"
    )

    for fund_key, spec in fund_keys.items():
        if not isinstance(spec, dict):
            raise PolicyError(
                f"finance_taxonomy.fund_keys.{fund_key} must be an object"
            )
        label = str(spec.get("label") or "").strip()
        if not label:
            raise PolicyError(
                f"finance_taxonomy.fund_keys.{fund_key}.label is required"
            )

        drk = spec.get("default_restriction_keys") or []
        if not isinstance(drk, list):
            raise PolicyError(
                "finance_taxonomy.fund_keys."
                f"{fund_key}.default_restriction_keys must be a list"
            )

        unknown = [
            x for x in _as_list_of_str(drk) if x not in restriction_keys
        ]
        if unknown:
            raise PolicyError(
                "finance_taxonomy.fund_keys."
                f"{fund_key}.default_restriction_keys has unknown keys: "
                f"{unknown}"
            )

    return warns, infos


def _check_funding_decisions() -> tuple[list[str], list[str]]:
    infos: list[str] = []
    warns: list[str] = []

    pol = load_policy_funding_decisions()
    tx = load_policy_finance_taxonomy()

    fund_keys = _as_key_set(tx.get("fund_keys"))
    restriction_keys = _as_key_set(tx.get("restriction_keys"))
    income_kinds = _as_key_set(tx.get("income_kinds"))
    expense_kinds = _as_key_set(tx.get("expense_kinds"))
    spending_classes = _as_key_set(tx.get("spending_classes"))

    approval_thresholds = pol.get("approval_thresholds") or {}
    intent_counting = pol.get("intent_counting") or {}
    eligibility_rules = pol.get("eligibility_rules") or []
    approval_rules = pol.get("approval_rules") or []
    preference_order = pol.get("preference_order") or []

    if not isinstance(approval_thresholds, dict):
        raise PolicyError(
            "funding_decisions.approval_thresholds must be an object"
        )
    if not isinstance(intent_counting, dict):
        raise PolicyError(
            "funding_decisions.intent_counting must be an object"
        )
    if not isinstance(eligibility_rules, list):
        raise PolicyError(
            "funding_decisions.eligibility_rules must be a list"
        )
    if not isinstance(approval_rules, list):
        raise PolicyError("funding_decisions.approval_rules must be a list")
    if not isinstance(preference_order, list):
        raise PolicyError("funding_decisions.preference_order must be a list")

    staff_limit = approval_thresholds.get("staff_limit_cents")
    admin_over = approval_thresholds.get("admin_over_cents")

    if not isinstance(staff_limit, int) or staff_limit < 0:
        raise PolicyError(
            "funding_decisions.approval_thresholds.staff_limit_cents "
            "must be an int >= 0"
        )
    if not isinstance(admin_over, int) or admin_over < 0:
        raise PolicyError(
            "funding_decisions.approval_thresholds.admin_over_cents "
            "must be an int >= 0"
        )
    if admin_over < staff_limit:
        warns.append(
            "funding_decisions admin_over_cents is below " "staff_limit_cents"
        )

    count_statuses = intent_counting.get("count_statuses") or []
    count_intent_kinds = intent_counting.get("count_intent_kinds") or []

    if not isinstance(count_statuses, list) or not count_statuses:
        raise PolicyError(
            "funding_decisions.intent_counting.count_statuses "
            "must be a non-empty list"
        )
    if not isinstance(count_intent_kinds, list) or not count_intent_kinds:
        raise PolicyError(
            "funding_decisions.intent_counting.count_intent_kinds "
            "must be a non-empty list"
        )

    seen_ids: set[str] = set()

    for rule in eligibility_rules:
        if not isinstance(rule, dict):
            raise PolicyError(
                "funding_decisions.eligibility_rules entries "
                "must be objects"
            )
        rid = str(rule.get("id") or "").strip()
        if not rid:
            raise PolicyError(
                "funding_decisions.eligibility_rules id is required"
            )
        if rid in seen_ids:
            raise PolicyError(f"funding_decisions duplicate rule id: {rid}")
        seen_ids.add(rid)

        for key in _as_list_of_str(rule.get("allow_fund_keys")):
            if key not in fund_keys:
                raise PolicyError(
                    f"funding_decisions rule {rid} references unknown "
                    f"fund_key: {key}"
                )
        for key in _as_list_of_str(rule.get("spending_classes_any")):
            if key not in spending_classes:
                raise PolicyError(
                    f"funding_decisions rule {rid} references unknown "
                    f"spending_class: {key}"
                )
        for key in _as_list_of_str(rule.get("income_kinds_any")):
            if key not in income_kinds:
                raise PolicyError(
                    f"funding_decisions rule {rid} references unknown "
                    f"income_kind: {key}"
                )
        for key in _as_list_of_str(rule.get("expense_kinds_any")):
            if key not in expense_kinds:
                raise PolicyError(
                    f"funding_decisions rule {rid} references unknown "
                    f"expense_kind: {key}"
                )
        for key in _as_list_of_str(rule.get("required_restrictions_all")):
            if key not in restriction_keys:
                raise PolicyError(
                    f"funding_decisions rule {rid} references unknown "
                    f"restriction_key: {key}"
                )
        for key in _as_list_of_str(rule.get("deny_if_restrictions_any")):
            if key not in restriction_keys:
                raise PolicyError(
                    f"funding_decisions rule {rid} references unknown "
                    f"restriction_key: {key}"
                )

    for rule in approval_rules:
        if not isinstance(rule, dict):
            raise PolicyError(
                "funding_decisions.approval_rules entries must be objects"
            )
        rid = str(rule.get("id") or "").strip()
        if not rid:
            raise PolicyError(
                "funding_decisions.approval_rules id is required"
            )
        if rid in seen_ids:
            raise PolicyError(f"funding_decisions duplicate rule id: {rid}")
        seen_ids.add(rid)

        for key in _as_list_of_str(rule.get("selected_fund_keys_any")):
            if key not in fund_keys:
                raise PolicyError(
                    f"funding_decisions approval rule {rid} references "
                    f"unknown fund_key: {key}"
                )

    for key in _as_list_of_str(preference_order):
        if key not in fund_keys:
            raise PolicyError(
                "funding_decisions.preference_order references "
                f"unknown fund_key: {key}"
            )

    infos.append(
        "funding decisions: "
        f"eligibility_rules={len(eligibility_rules)} "
        f"approval_rules={len(approval_rules)} "
        f"preference_order={len(preference_order)}"
    )

    return warns, infos


def _check_entity_roles() -> tuple[list[str], list[str]]:
    infos: list[str] = []
    warns: list[str] = []

    doc = load_governance_policy("entity_roles") or {}

    domain_roles = doc.get("domain_roles") or []
    rules = doc.get("assignment_rules") or {}

    if not isinstance(domain_roles, list) or not domain_roles:
        raise PolicyError(
            "entity_roles.domain_roles must be a non-empty list"
        )
    if not isinstance(rules, dict):
        raise PolicyError("entity_roles.assignment_rules must be an object")

    infos.append(
        "entity roles: "
        f"domain_roles={len(domain_roles)} "
        f"assignment_rules={len(rules)}"
    )

    return warns, infos


def policy_health_report() -> tuple[list[str], list[str]]:
    warns: list[str] = []
    infos: list[str] = []

    for fn in (
        _check_entity_roles,
        _check_finance_taxonomy,
        _check_funding_decisions,
    ):
        w, i = fn()
        warns.extend(w)
        infos.extend(i)

    return warns, infos
