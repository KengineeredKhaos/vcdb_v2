# app/slices/governance/services_funding_decisions.py

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.extensions.policies import (
    load_policy_finance_taxonomy,
    load_policy_funding_decisions,
)


@dataclass(frozen=True)
class _FundKey:
    key: str
    label: str
    archetype: str
    default_restriction_keys: tuple[str, ...]


def _stable_json(data: object) -> str:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = _stable_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _as_tuple_str(values: object) -> tuple[str, ...]:
    out: list[str] = []
    for v in values or ():
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return tuple(out)


def _taxonomy_fund_map() -> dict[str, _FundKey]:
    tx = load_policy_finance_taxonomy()

    out: dict[str, _FundKey] = {}
    fund_keys = tx.get("fund_keys") or {}

    if not isinstance(fund_keys, dict):
        raise ValueError("finance_taxonomy.fund_keys must be an object")

    for key, spec in fund_keys.items():
        spec = spec or {}
        out[str(key)] = _FundKey(
            key=str(key),
            label=str(spec.get("label") or key),
            archetype=str(spec.get("archetype") or ""),
            default_restriction_keys=tuple(
                spec.get("default_restriction_keys") or ()
            ),
        )

    return out


def _normalize_req(raw_req: dict[str, Any]) -> dict[str, Any]:
    op = str(raw_req.get("op") or "").strip()
    if not op:
        raise ValueError("op is required")

    amount_cents = raw_req.get("amount_cents")
    if not isinstance(amount_cents, int):
        raise ValueError("amount_cents must be an int")
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")

    return {
        "op": op,
        "amount_cents": amount_cents,
        "funding_demand_ulid": raw_req.get("funding_demand_ulid"),
        "project_ulid": raw_req.get("project_ulid"),
        "spending_class": raw_req.get("spending_class"),
        "income_kind": raw_req.get("income_kind"),
        "expense_kind": raw_req.get("expense_kind"),
        "restriction_keys": _as_tuple_str(raw_req.get("restriction_keys")),
        "demand_eligible_fund_keys": _as_tuple_str(
            raw_req.get("demand_eligible_fund_keys")
        ),
        "tag_any": _as_tuple_str(raw_req.get("tag_any")),
        "selected_fund_key": (
            str(raw_req["selected_fund_key"]).strip()
            if raw_req.get("selected_fund_key")
            else None
        ),
        "actor_rbac_roles": _as_tuple_str(raw_req.get("actor_rbac_roles")),
        "actor_domain_roles": _as_tuple_str(
            raw_req.get("actor_domain_roles")
        ),
    }


def _normalize_ops_float_req(raw_req: dict[str, Any]) -> dict[str, Any]:
    action = str(raw_req.get("action") or "allocate").strip()
    if action not in {"allocate", "repay", "forgive"}:
        raise ValueError("action must be allocate|repay|forgive")

    support_mode = str(raw_req.get("support_mode") or "").strip()
    if support_mode not in {"seed", "backfill", "bridge"}:
        raise ValueError("support_mode must be seed|backfill|bridge")

    amount_cents = raw_req.get("amount_cents")
    if not isinstance(amount_cents, int):
        raise ValueError("amount_cents must be an int")
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")

    fund_key = str(raw_req.get("fund_key") or "").strip()
    if not fund_key:
        raise ValueError("fund_key is required")

    return {
        "action": action,
        "support_mode": support_mode,
        "amount_cents": amount_cents,
        "fund_key": fund_key,
        "source_funding_demand_ulid": raw_req.get(
            "source_funding_demand_ulid"
        ),
        "source_project_ulid": raw_req.get("source_project_ulid"),
        "dest_funding_demand_ulid": raw_req.get("dest_funding_demand_ulid"),
        "dest_project_ulid": raw_req.get("dest_project_ulid"),
        "spending_class": raw_req.get("spending_class"),
        "tag_any": _as_tuple_str(raw_req.get("tag_any")),
        "dest_eligible_fund_keys": _as_tuple_str(
            raw_req.get("dest_eligible_fund_keys")
        ),
        "actor_rbac_roles": _as_tuple_str(raw_req.get("actor_rbac_roles")),
        "actor_domain_roles": _as_tuple_str(
            raw_req.get("actor_domain_roles")
        ),
    }


def _rule_ops_match(rule: dict[str, Any], op: str) -> bool:
    ops = set(_as_tuple_str(rule.get("ops")))
    return not ops or op in ops


def _any_match(rule_vals: object, value: str | None) -> bool:
    vals = set(_as_tuple_str(rule_vals))
    if not vals:
        return True
    if not value:
        return False
    return value in vals


def _required_tags_match(rule: dict[str, Any], tags: tuple[str, ...]) -> bool:
    required = set(_as_tuple_str(rule.get("required_tags_any")))
    if not required:
        return True
    return bool(required.intersection(tags))


def _required_restrictions_match(
    rule: dict[str, Any],
    restriction_keys: tuple[str, ...],
) -> bool:
    required = set(_as_tuple_str(rule.get("required_restrictions_all")))
    if not required:
        return True
    have = set(restriction_keys)
    return required.issubset(have)


def _deny_restrictions_hit(
    rule: dict[str, Any],
    restriction_keys: tuple[str, ...],
) -> bool:
    deny_any = set(_as_tuple_str(rule.get("deny_if_restrictions_any")))
    if not deny_any:
        return False
    return bool(deny_any.intersection(restriction_keys))


def _rule_matches(rule: dict[str, Any], req: dict[str, Any]) -> bool:
    return (
        bool(rule.get("enabled", True))
        and _rule_ops_match(rule, req["op"])
        and _any_match(
            rule.get("spending_classes_any"), req["spending_class"]
        )
        and _any_match(rule.get("income_kinds_any"), req["income_kind"])
        and _any_match(rule.get("expense_kinds_any"), req["expense_kind"])
        and _required_tags_match(rule, req["tag_any"])
        and _required_restrictions_match(rule, req["restriction_keys"])
        and not _deny_restrictions_hit(rule, req["restriction_keys"])
    )


def _sort_funds(
    fund_keys: set[str],
    preference_order: tuple[str, ...],
) -> tuple[str, ...]:
    pref_index = {k: i for i, k in enumerate(preference_order)}
    return tuple(
        sorted(
            fund_keys,
            key=lambda x: (pref_index.get(x, 999999), x),
        )
    )


def _eligible_fund_keys(
    req: dict[str, Any],
    policy: dict[str, Any],
    fund_map: dict[str, _FundKey],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    matched_rule_ids: list[str] = []
    reason_codes: list[str] = []
    eligible: set[str] = set()

    rules = sorted(
        policy.get("eligibility_rules") or (),
        key=lambda r: int(r.get("priority", 999999)),
    )

    for rule in rules:
        if not _rule_matches(rule, req):
            continue
        matched_rule_ids.append(str(rule["id"]))
        reason_codes.append(f"rule_match:{rule['id']}")
        for fund_key in _as_tuple_str(rule.get("allow_fund_keys")):
            if fund_key in fund_map:
                eligible.add(fund_key)

    caller_hint = set(req["demand_eligible_fund_keys"])
    if caller_hint:
        eligible = (
            eligible.intersection(caller_hint) if eligible else caller_hint
        )
        reason_codes.append("demand_hint_applied")

    if not eligible and caller_hint:
        reason_codes.append("eligible_from_demand_hint_only")

    preference_order = _as_tuple_str(policy.get("preference_order"))
    ordered = _sort_funds(eligible, preference_order)

    if not ordered:
        reason_codes.append("no_eligible_funds")

    return ordered, tuple(reason_codes), tuple(matched_rule_ids)


def _approval_requirements(
    req: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    approvals: list[str] = []
    reason_codes: list[str] = []
    matched_rule_ids: list[str] = []

    rules = sorted(
        policy.get("approval_rules") or (),
        key=lambda r: int(r.get("priority", 999999)),
    )

    selected_fund_key = req["selected_fund_key"]

    for rule in rules:
        if not bool(rule.get("enabled", True)):
            continue
        if not _rule_ops_match(rule, req["op"]):
            continue

        min_amount_cents = int(rule.get("min_amount_cents") or 0)
        if req["amount_cents"] < min_amount_cents:
            continue

        fund_scope = set(_as_tuple_str(rule.get("selected_fund_keys_any")))
        if fund_scope and selected_fund_key not in fund_scope:
            continue

        matched_rule_ids.append(str(rule["id"]))
        reason_codes.append(f"approval_rule:{rule['id']}")

        for role in _as_tuple_str(rule.get("required_approvals")):
            if role not in approvals:
                approvals.append(role)

    return tuple(approvals), tuple(reason_codes), tuple(matched_rule_ids)


def preview_funding_decision(raw_req: dict[str, Any]) -> dict[str, Any]:
    req = _normalize_req(raw_req)
    policy = load_policy_funding_decisions()
    fund_map = _taxonomy_fund_map()

    (
        eligible_fund_keys,
        eligibility_reasons,
        eligibility_rule_ids,
    ) = _eligible_fund_keys(req, policy, fund_map)

    allowed = bool(eligible_fund_keys)
    selected_fund_key = req["selected_fund_key"]

    reason_codes = list(eligibility_reasons)
    matched_rule_ids = list(eligibility_rule_ids)
    required_approvals: tuple[str, ...] = ()

    if selected_fund_key:
        if selected_fund_key not in eligible_fund_keys:
            allowed = False
            reason_codes.append("selected_fund_not_eligible")
        else:
            reason_codes.append("selected_fund_confirmed")
            (
                approvals,
                approval_reasons,
                approval_rule_ids,
            ) = _approval_requirements(req, policy)
            required_approvals = approvals
            reason_codes.extend(approval_reasons)
            matched_rule_ids.extend(approval_rule_ids)

    fp_payload = {
        "req": req,
        "allowed": allowed,
        "eligible_fund_keys": eligible_fund_keys,
        "selected_fund_key": selected_fund_key,
        "required_approvals": required_approvals,
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "policy_version": int(policy.get("version") or 1),
    }

    return {
        "allowed": allowed,
        "eligible_fund_keys": eligible_fund_keys,
        "selected_fund_key": selected_fund_key,
        "required_approvals": required_approvals,
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "decision_fingerprint": _fingerprint(fp_payload),
    }


def preview_ops_float(raw_req: dict[str, Any]) -> dict[str, Any]:
    req = _normalize_ops_float_req(raw_req)
    policy = load_policy_funding_decisions()
    fund_map = _taxonomy_fund_map()

    if req["fund_key"] not in fund_map:
        raise ValueError(f"unknown fund_key: {req['fund_key']}")

    allowed = True
    reason_codes: list[str] = [
        f"ops_float_action:{req['action']}",
        f"ops_float_mode:{req['support_mode']}",
    ]
    matched_rule_ids: list[str] = []
    required_approvals: list[str] = []

    eligible = tuple(req["dest_eligible_fund_keys"])
    if eligible and req["fund_key"] not in eligible:
        allowed = False
        reason_codes.append("selected_fund_not_eligible_for_destination")
    else:
        reason_codes.append("selected_fund_confirmed")

    rules = policy.get("ops_float_rules") or {}
    auto_allowed = set(_as_tuple_str(rules.get("auto_allowed_modes")))
    governor_required = set(
        _as_tuple_str(rules.get("governor_required_modes"))
    )
    auto_actions = set(_as_tuple_str(rules.get("auto_allowed_actions")))
    governor_required_actions = set(
        _as_tuple_str(rules.get("governor_required_actions"))
    )
    if req["action"] == "allocate":
        eligible = tuple(req["dest_eligible_fund_keys"])
        if eligible and req["fund_key"] not in eligible:
            allowed = False
            reason_codes.append("selected_fund_not_eligible_for_destination")
        else:
            reason_codes.append("selected_fund_confirmed")

        if req["support_mode"] in auto_allowed:
            reason_codes.append("ops_float_auto_allowed")

        needs_governor = req["support_mode"] in governor_required
        has_governor = "governor" in req["actor_domain_roles"]
        if needs_governor and not has_governor:
            matched_rule_ids.append(
                f"ops_float_requires_governor:{req['support_mode']}"
            )
            required_approvals.append("governor")
            reason_codes.append("ops_float_governor_required")
        elif needs_governor:
            matched_rule_ids.append(
                f"ops_float_requires_governor:{req['support_mode']}"
            )
            reason_codes.append("ops_float_governor_present")
    elif req["action"] == "repay":
        if "repay" in auto_actions:
            reason_codes.append("ops_float_repay_auto_allowed")
    elif req["action"] == "forgive":
        needs_governor = "forgive" in governor_required_actions
        has_governor = "governor" in req["actor_domain_roles"]
        if needs_governor and not has_governor:
            matched_rule_ids.append("ops_float_forgive_requires_governor")
            required_approvals.append("governor")
            reason_codes.append("ops_float_governor_required")
        elif needs_governor:
            matched_rule_ids.append("ops_float_forgive_requires_governor")
            reason_codes.append("ops_float_governor_present")
  

    fp_payload = {
        "req": req,
        "allowed": allowed,
        "required_approvals": tuple(required_approvals),
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "policy_version": int(policy.get("meta", {}).get("version") or 1),
    }

    return {
        "allowed": allowed,
        "eligible_fund_keys": (req["fund_key"],),
        "selected_fund_key": req["fund_key"],
        "required_approvals": tuple(required_approvals),
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "decision_fingerprint": _fingerprint(fp_payload),
    }
