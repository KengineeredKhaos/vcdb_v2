# app/extensions/policy_health.py

from __future__ import annotations

from app.extensions.policies import (
    load_governance_policy,
    load_policy_entity_roles,
    load_policy_finance_controls,
    load_policy_finance_selectors,
    load_policy_finance_taxonomy,
    load_policy_funding_source_controls,
    load_policy_records_lifecycle,
)


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

    fund_codes = pol.get("fund_codes") or {}
    restriction_keys = pol.get("restriction_keys") or {}
    income_kinds = pol.get("income_kinds") or {}
    expense_kinds = pol.get("expense_kinds") or {}
    spending_classes = pol.get("spending_classes") or {}

    if not isinstance(fund_codes, dict) or not fund_codes:
        raise PolicyError(
            "finance_taxonomy.fund_codes must be a non-empty object"
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
        f"fund_codes={len(fund_codes)} "
        f"restriction_keys={len(restriction_keys)} "
        f"income_kinds={len(income_kinds)} "
        f"expense_kinds={len(expense_kinds)} "
        f"spending_classes={len(spending_classes)}"
    )

    for fund_code, spec in fund_codes.items():
        if not isinstance(spec, dict):
            raise PolicyError(
                f"finance_taxonomy.fund_codes.{fund_code} must be an object"
            )
        label = str(spec.get("label") or "").strip()
        if not label:
            raise PolicyError(
                f"finance_taxonomy.fund_codes.{fund_code}.label is required"
            )

        drk = spec.get("default_restriction_keys") or []
        if not isinstance(drk, list):
            raise PolicyError(
                "finance_taxonomy.fund_codes."
                f"{fund_code}.default_restriction_keys must be a list"
            )

        unknown = [
            x for x in _as_list_of_str(drk) if x not in restriction_keys
        ]
        if unknown:
            raise PolicyError(
                "finance_taxonomy.fund_codes."
                f"{fund_code}.default_restriction_keys has unknown keys: "
                f"{unknown}"
            )

    return warns, infos


def _check_finance_controls() -> tuple[list[str], list[str]]:
    infos: list[str] = []
    warns: list[str] = []

    pol = load_policy_finance_controls()
    tx = load_policy_finance_taxonomy()

    fund_codes = _as_key_set(tx.get("fund_codes"))
    approval_rules = pol.get("approval_rules") or []
    budget_periods = pol.get("budget_periods") or []
    budget_caps = pol.get("budget_caps") or []

    staff_cap = pol.get("staff_cap_cents")

    if not isinstance(staff_cap, int) or staff_cap < 0:
        raise PolicyError(
            "finance_controls.staff_cap_cents must be an int >= 0"
        )
    if not isinstance(approval_rules, list):
        raise PolicyError("finance_controls.approval_rules must be a list")
    if not isinstance(budget_periods, list):
        raise PolicyError("finance_controls.budget_periods must be a list")
    if not isinstance(budget_caps, list):
        raise PolicyError("finance_controls.budget_caps must be a list")

    seen_ids: set[str] = set()

    for rule in approval_rules:
        if not isinstance(rule, dict):
            raise PolicyError(
                "finance_controls.approval_rules entries must be objects"
            )

        rid = str(rule.get("rule_id") or "").strip()
        if not rid:
            raise PolicyError(
                "finance_controls.approval_rules rule_id is required"
            )
        if rid in seen_ids:
            raise PolicyError(
                f"finance_controls duplicate approval rule id: {rid}"
            )
        seen_ids.add(rid)

        match = rule.get("match") or {}
        if not isinstance(match, dict):
            raise PolicyError(
                f"finance_controls approval rule {rid} match must be an object"
            )

        for key in _as_list_of_str(match.get("selected_fund_codes_any")):
            if key not in fund_codes:
                raise PolicyError(
                    f"finance_controls approval rule {rid} references "
                    f"unknown fund_code: {key}"
                )

    infos.append(
        "finance controls: "
        f"approval_rules={len(approval_rules)} "
        f"budget_periods={len(budget_periods)} "
        f"budget_caps={len(budget_caps)}"
    )

    return warns, infos


def _check_finance_selectors() -> tuple[list[str], list[str]]:
    infos: list[str] = []
    warns: list[str] = []

    pol = load_policy_finance_selectors()
    tx = load_policy_finance_taxonomy()
    sc = load_policy_funding_source_controls()

    fund_codes = _as_key_set(tx.get("fund_codes"))
    restriction_keys = _as_key_set(tx.get("restriction_keys"))
    income_kinds = _as_key_set(tx.get("income_kinds"))
    expense_kinds = _as_key_set(tx.get("expense_kinds"))
    spending_classes = _as_key_set(tx.get("spending_classes"))
    source_profiles = _as_key_set(sc.get("source_profiles"))
    source_kinds = _as_key_set(sc.get("source_kinds"))

    rules = pol.get("rules") or []
    if not isinstance(rules, list):
        raise PolicyError("finance_selectors.rules must be a list")

    seen_ids: set[str] = set()

    for rule in rules:
        if not isinstance(rule, dict):
            raise PolicyError(
                "finance_selectors.rules entries must be objects"
            )

        rid = str(rule.get("rule_id") or "").strip()
        if not rid:
            raise PolicyError("finance_selectors rule_id is required")
        if rid in seen_ids:
            raise PolicyError(f"finance_selectors duplicate rule id: {rid}")
        seen_ids.add(rid)

        for key in _as_list_of_str(rule.get("allow_fund_codes")):
            if key not in fund_codes:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"fund_code: {key}"
                )

        for key in _as_list_of_str(rule.get("prefer_fund_codes")):
            if key not in fund_codes:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"fund_code: {key}"
                )

        match = rule.get("match") or {}
        if not isinstance(match, dict):
            raise PolicyError(
                f"finance_selectors rule {rid} match must be an object"
            )

        for key in _as_list_of_str(match.get("source_profile_any")):
            if key not in source_profiles:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"source_profile: {key}"
                )
        for key in _as_list_of_str(match.get("source_kind_any")):
            if key not in source_kinds:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"source_kind: {key}"
                )
        for key in _as_list_of_str(match.get("spending_class")):
            if key not in spending_classes:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"spending_class: {key}"
                )
        for key in _as_list_of_str(match.get("income_kind")):
            if key not in income_kinds:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"income_kind: {key}"
                )
        for key in _as_list_of_str(match.get("expense_kind")):
            if key not in expense_kinds:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"expense_kind: {key}"
                )
        for key in _as_list_of_str(match.get("restriction_keys_any")):
            if key not in restriction_keys:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"restriction_key: {key}"
                )
        for key in _as_list_of_str(match.get("restriction_keys_all")):
            if key not in restriction_keys:
                raise PolicyError(
                    f"finance_selectors rule {rid} references unknown "
                    f"restriction_key: {key}"
                )

    infos.append(f"finance selectors: rules={len(rules)}")

    return warns, infos


def _check_funding_source_controls() -> tuple[list[str], list[str]]:
    infos: list[str] = []
    warns: list[str] = []

    pol = load_policy_funding_source_controls()
    tx = load_policy_finance_taxonomy()

    source_kinds = _as_key_set(pol.get("source_kinds"))
    support_modes = _as_key_set(pol.get("support_modes"))
    approval_postures = _as_key_set(pol.get("approval_postures"))
    source_profiles = pol.get("source_profiles") or {}

    restriction_keys = _as_key_set(tx.get("restriction_keys"))
    expense_kinds = _as_key_set(tx.get("expense_kinds"))
    spending_classes = _as_key_set(tx.get("spending_classes"))

    if not source_kinds:
        raise PolicyError(
            "funding_source_controls.source_kinds must be a non-empty object"
        )
    if not support_modes:
        raise PolicyError(
            "funding_source_controls.support_modes must be a non-empty object"
        )
    if not approval_postures:
        raise PolicyError(
            "funding_source_controls.approval_postures must be a non-empty object"
        )
    if not isinstance(source_profiles, dict) or not source_profiles:
        raise PolicyError(
            "funding_source_controls.source_profiles must be a non-empty object"
        )

    for key, spec in source_profiles.items():
        if not isinstance(spec, dict):
            raise PolicyError(
                f"funding_source_controls.source_profiles.{key} "
                "must be an object"
            )

        profile_key = str(spec.get("source_profile_key") or "").strip()
        if not profile_key:
            raise PolicyError(
                f"funding_source_controls.source_profiles.{key} "
                "source_profile_key is required"
            )
        if profile_key != key:
            raise PolicyError(
                f"funding_source_controls.source_profiles.{key} "
                "source_profile_key must match the enclosing key"
            )

        src_kind = str(spec.get("source_kind") or "").strip()
        if src_kind not in source_kinds:
            raise PolicyError(
                f"funding_source_controls.source_profiles.{key} "
                f"references unknown source_kind: {src_kind}"
            )

        mode = str(spec.get("support_mode") or "").strip()
        if mode not in support_modes:
            raise PolicyError(
                f"funding_source_controls.source_profiles.{key} "
                f"references unknown support_mode: {mode}"
            )

        posture = str(spec.get("approval_posture") or "").strip()
        if posture not in approval_postures:
            raise PolicyError(
                f"funding_source_controls.source_profiles.{key} "
                f"references unknown approval_posture: {posture}"
            )

        for rk in _as_list_of_str(spec.get("default_restriction_keys")):
            if rk not in restriction_keys:
                raise PolicyError(
                    f"funding_source_controls.source_profiles.{key} "
                    f"references unknown restriction_key: {rk}"
                )

        for mode_key in _as_list_of_str(
            spec.get("allowed_ops_support_modes")
        ):
            if mode_key not in support_modes:
                raise PolicyError(
                    f"funding_source_controls.source_profiles.{key} "
                    f"references unknown allowed_ops_support_mode: {mode_key}"
                )

        for ek in _as_list_of_str(spec.get("prohibited_expense_kinds_any")):
            if ek not in expense_kinds:
                raise PolicyError(
                    f"funding_source_controls.source_profiles.{key} "
                    f"references unknown expense_kind: {ek}"
                )

        for sk in _as_list_of_str(
            spec.get("prohibited_spending_classes_any")
        ):
            if sk not in spending_classes:
                raise PolicyError(
                    f"funding_source_controls.source_profiles.{key} "
                    f"references unknown spending_class: {sk}"
                )

    infos.append(
        "funding source controls: "
        f"source_kinds={len(source_kinds)} "
        f"support_modes={len(support_modes)} "
        f"approval_postures={len(approval_postures)} "
        f"source_profiles={len(source_profiles)}"
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
        _check_finance_controls,
        _check_finance_selectors,
        _check_funding_source_controls,
    ):
        w, i = fn()
        warns.extend(w)
        infos.extend(i)

    return warns, infos
