from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.extensions.policies import (
    load_governance_policy,
    load_policy_finance_taxonomy,
)


@dataclass(frozen=True)
class _FundKey:
    key: str
    label: str
    archetype: str
    default_restriction_keys: tuple[str, ...]


@dataclass(frozen=True)
class _SourceProfile:
    key: str
    source_kind: str
    support_mode: str
    approval_posture: str
    default_restriction_keys: tuple[str, ...]
    bridge_allowed: bool
    repayment_expectation: str
    forgiveness_rule: str
    auto_ops_bridge_on_publish: bool
    prohibited_spending_classes_any: tuple[str, ...]
    prohibited_expense_kinds_any: tuple[str, ...]


@dataclass(frozen=True)
class FundingSourceProfileSummary:
    key: str
    source_kind: str
    support_mode: str
    approval_posture: str
    default_restriction_keys: tuple[str, ...]
    bridge_allowed: bool
    repayment_expectation: str
    forgiveness_rule: str
    auto_ops_bridge_on_publish: bool


_OPS_PROFILE_BY_MODE = {
    "seed": "ops_seed_board_motion",
    "backfill": "ops_backfill_board_motion",
    "bridge": "ops_bridge_preapproved",
}

_OP_KEY_BY_ACTION = {
    "allocate": "ops_allocate",
    "repay": "ops_repay",
    "forgive": "ops_forgive",
}


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
    for value in values or ():
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _load_policy_doc(policy_key: str) -> dict[str, Any]:
    doc = load_governance_policy(policy_key) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{policy_key} policy must be an object")
    return doc


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


def _source_profile_map() -> dict[str, _SourceProfile]:
    doc = _load_policy_doc("funding_source_controls")
    raw_profiles = doc.get("source_profiles") or {}
    if not isinstance(raw_profiles, dict):
        raise ValueError(
            "funding_source_controls.source_profiles must be an object"
        )

    out: dict[str, _SourceProfile] = {}
    for key, spec in raw_profiles.items():
        spec = spec or {}
        out[str(key)] = _SourceProfile(
            key=str(key),
            source_kind=str(spec.get("source_kind") or ""),
            support_mode=str(spec.get("support_mode") or ""),
            approval_posture=str(spec.get("approval_posture") or ""),
            default_restriction_keys=_as_tuple_str(
                spec.get("default_restriction_keys")
            ),
            bridge_allowed=bool(spec.get("bridge_allowed", False)),
            repayment_expectation=str(
                spec.get("repayment_expectation") or "none"
            ),
            forgiveness_rule=str(
                spec.get("forgiveness_rule") or "not_applicable"
            ),
            auto_ops_bridge_on_publish=bool(
                spec.get("auto_ops_bridge_on_publish", False)
            ),
            prohibited_spending_classes_any=_as_tuple_str(
                spec.get("prohibited_spending_classes_any")
            ),
            prohibited_expense_kinds_any=_as_tuple_str(
                spec.get("prohibited_expense_kinds_any")
            ),
        )
    return out


def _get_source_profile_or_raise(
    profile_key: str | None,
) -> _SourceProfile | None:
    if not profile_key:
        return None
    profiles = _source_profile_map()
    try:
        return profiles[profile_key]
    except KeyError as exc:
        raise ValueError(
            f"unknown source_profile_key: {profile_key}"
        ) from exc


def _merge_restriction_keys(
    explicit_keys: tuple[str, ...],
    profile: _SourceProfile | None,
) -> tuple[str, ...]:
    merged: list[str] = list(explicit_keys)
    if profile is None:
        return tuple(merged)
    for key in profile.default_restriction_keys:
        if key not in merged:
            merged.append(key)
    return tuple(merged)


def _normalize_req(raw_req: dict[str, Any]) -> dict[str, Any]:
    op = str(raw_req.get("op") or "").strip()
    if not op:
        raise ValueError("op is required")

    amount_cents = raw_req.get("amount_cents")
    if not isinstance(amount_cents, int):
        raise ValueError("amount_cents must be an int")
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")

    ops_support_planned = raw_req.get("ops_support_planned")
    if ops_support_planned is not None and not isinstance(
        ops_support_planned, bool
    ):
        raise ValueError("ops_support_planned must be a bool when provided")

    return {
        "op": op,
        "amount_cents": amount_cents,
        "funding_demand_ulid": raw_req.get("funding_demand_ulid"),
        "project_ulid": raw_req.get("project_ulid"),
        "spending_class": raw_req.get("spending_class"),
        "income_kind": raw_req.get("income_kind"),
        "expense_kind": raw_req.get("expense_kind"),
        "source_profile_key": (
            str(raw_req["source_profile_key"]).strip()
            if raw_req.get("source_profile_key")
            else None
        ),
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
        "ops_support_planned": ops_support_planned,
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

    ops_support_planned = raw_req.get("ops_support_planned")
    if ops_support_planned is not None and not isinstance(
        ops_support_planned, bool
    ):
        raise ValueError("ops_support_planned must be a bool when provided")

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
        "ops_support_planned": ops_support_planned,
        "actor_rbac_roles": _as_tuple_str(raw_req.get("actor_rbac_roles")),
        "actor_domain_roles": _as_tuple_str(
            raw_req.get("actor_domain_roles")
        ),
    }


def _match_intersection(
    values: object,
    have_values: tuple[str | None, ...] | tuple[str, ...],
) -> bool:
    required = set(_as_tuple_str(values))
    if not required:
        return True
    have = set(_as_tuple_str(have_values))
    return bool(required.intersection(have))


def _match_all(
    values: object,
    have_values: tuple[str, ...],
) -> bool:
    required = set(_as_tuple_str(values))
    if not required:
        return True
    have = set(_as_tuple_str(have_values))
    return required.issubset(have)


def _selector_rule_matches(
    rule: dict[str, Any],
    req: dict[str, Any],
    profile: _SourceProfile | None,
) -> bool:
    match = rule.get("match") or {}

    if not _match_intersection(match.get("op"), (req["op"],)):
        return False
    if not _match_intersection(
        match.get("source_profile_any"),
        (req["source_profile_key"],),
    ):
        return False
    if not _match_intersection(
        match.get("source_kind_any"),
        (profile.source_kind if profile else None,),
    ):
        return False
    if not _match_intersection(
        match.get("spending_class"),
        (req["spending_class"],),
    ):
        return False
    if not _match_intersection(
        match.get("income_kind"),
        (req["income_kind"],),
    ):
        return False
    if not _match_intersection(
        match.get("expense_kind"),
        (req["expense_kind"],),
    ):
        return False
    if not _match_intersection(match.get("tag_any"), req["tag_any"]):
        return False
    if not _match_intersection(
        match.get("restriction_keys_any"),
        req["restriction_keys"],
    ):
        return False
    if not _match_all(
        match.get("restriction_keys_all"),
        req["restriction_keys"],
    ):
        return False

    min_amount = match.get("amount_cents_gte")
    if min_amount is not None and req["amount_cents"] < int(min_amount):
        return False

    max_amount = match.get("amount_cents_lte")
    if max_amount is not None and req["amount_cents"] > int(max_amount):
        return False

    return True


def _order_funds(
    eligible: set[str],
    preferred: list[str],
) -> tuple[str, ...]:
    ordered: list[str] = []
    for key in preferred:
        if key in eligible and key not in ordered:
            ordered.append(key)
    for key in sorted(eligible):
        if key not in ordered:
            ordered.append(key)
    return tuple(ordered)


def _eligible_fund_keys(
    req: dict[str, Any],
    selectors: dict[str, Any],
    fund_map: dict[str, _FundKey],
    profile: _SourceProfile | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    matched_rule_ids: list[str] = []
    reason_codes: list[str] = []
    eligible: set[str] = set()
    preferred: list[str] = []

    rules = sorted(
        selectors.get("rules") or (),
        key=lambda rule: int(rule.get("priority", 999999)),
    )

    for rule in rules:
        if not _selector_rule_matches(rule, req, profile):
            continue

        rule_id = str(rule.get("rule_id") or "")
        matched_rule_ids.append(rule_id)
        reason_codes.append(f"selector_rule:{rule_id}")

        for fund_key in _as_tuple_str(rule.get("allow_fund_keys")):
            if fund_key in fund_map:
                eligible.add(fund_key)

        for fund_key in _as_tuple_str(rule.get("prefer_fund_keys")):
            if fund_key in fund_map and fund_key not in preferred:
                preferred.append(fund_key)

    caller_hint = set(req["demand_eligible_fund_keys"])
    if caller_hint:
        eligible = (
            eligible.intersection(caller_hint) if eligible else caller_hint
        )
        reason_codes.append("demand_hint_applied")

    ordered = _order_funds(eligible, preferred)
    if not ordered:
        reason_codes.append("no_eligible_funds")

    return ordered, tuple(reason_codes), tuple(matched_rule_ids)


def _approval_requirements(
    req: dict[str, Any],
    controls: dict[str, Any],
    profile: _SourceProfile | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    approvals: list[str] = []
    reason_codes: list[str] = []
    matched_rule_ids: list[str] = []

    selected_fund_key = req.get("selected_fund_key")
    approval_posture = profile.approval_posture if profile else None

    rules = sorted(
        controls.get("approval_rules") or (),
        key=lambda rule: int(rule.get("priority", 999999)),
    )

    for rule in rules:
        match = rule.get("match") or {}

        if not _match_intersection(match.get("op"), (req["op"],)):
            continue

        amount_gt = match.get("amount_cents_gt")
        if amount_gt is not None and req["amount_cents"] <= int(amount_gt):
            continue

        fund_scope = set(_as_tuple_str(match.get("selected_fund_keys_any")))
        if fund_scope and selected_fund_key not in fund_scope:
            continue

        posture_scope = set(_as_tuple_str(match.get("approval_posture_any")))
        if posture_scope and approval_posture not in posture_scope:
            continue

        planned = match.get("ops_support_planned")
        if (
            planned is not None
            and req.get("ops_support_planned") is not planned
        ):
            continue

        rule_id = str(rule.get("rule_id") or "")
        matched_rule_ids.append(rule_id)

        reason = str(rule.get("reason_code") or f"approval_rule:{rule_id}")
        reason_codes.append(reason)

        for role in _as_tuple_str(rule.get("required_approvals")):
            if role not in approvals:
                approvals.append(role)

    return tuple(approvals), tuple(reason_codes), tuple(matched_rule_ids)


def _profile_conflicts(
    req: dict[str, Any],
    profile: _SourceProfile | None,
) -> tuple[str, ...]:
    if profile is None:
        return ()

    reasons: list[str] = []

    if (
        req.get("spending_class")
        and req["spending_class"] in profile.prohibited_spending_classes_any
    ):
        reasons.append("source_profile_blocks_spending_class")

    if (
        req.get("expense_kind")
        and req["expense_kind"] in profile.prohibited_expense_kinds_any
    ):
        reasons.append("source_profile_blocks_expense_kind")

    return tuple(reasons)


def preview_funding_decision(raw_req: dict[str, Any]) -> dict[str, Any]:
    req = _normalize_req(raw_req)
    profile = _get_source_profile_or_raise(req["source_profile_key"])

    req["restriction_keys"] = _merge_restriction_keys(
        req["restriction_keys"],
        profile,
    )

    selectors = _load_policy_doc("finance_selectors")
    controls = _load_policy_doc("finance_controls")
    fund_map = _taxonomy_fund_map()

    (
        eligible_fund_keys,
        selector_reasons,
        selector_rule_ids,
    ) = _eligible_fund_keys(
        req,
        selectors,
        fund_map,
        profile,
    )

    allowed = bool(eligible_fund_keys)
    reason_codes = list(selector_reasons)
    matched_rule_ids = list(selector_rule_ids)

    if profile is not None:
        reason_codes.append(f"source_profile:{profile.key}")

    for reason in _profile_conflicts(req, profile):
        allowed = False
        reason_codes.append(reason)

    selected_fund_key = req["selected_fund_key"]
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
            ) = _approval_requirements(
                req,
                controls,
                profile,
            )
            required_approvals = approvals
            reason_codes.extend(approval_reasons)
            matched_rule_ids.extend(approval_rule_ids)

    fp_payload = {
        "req": req,
        "source_profile_key": profile.key if profile else None,
        "allowed": allowed,
        "eligible_fund_keys": eligible_fund_keys,
        "selected_fund_key": selected_fund_key,
        "required_approvals": required_approvals,
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "selectors_version": int(
            selectors.get("meta", {}).get("version") or 1
        ),
        "controls_version": int(controls.get("meta", {}).get("version") or 1),
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
    fund_map = _taxonomy_fund_map()

    if req["fund_key"] not in fund_map:
        raise ValueError(f"unknown fund_key: {req['fund_key']}")

    profile_key = _OPS_PROFILE_BY_MODE[req["support_mode"]]
    profile = _get_source_profile_or_raise(profile_key)
    selectors = _load_policy_doc("finance_selectors")
    controls = _load_policy_doc("finance_controls")

    generic_req = {
        "op": _OP_KEY_BY_ACTION[req["action"]],
        "amount_cents": req["amount_cents"],
        "funding_demand_ulid": req["dest_funding_demand_ulid"],
        "project_ulid": req["dest_project_ulid"],
        "spending_class": req["spending_class"],
        "income_kind": None,
        "expense_kind": None,
        "source_profile_key": profile_key,
        "restriction_keys": (),
        "demand_eligible_fund_keys": req["dest_eligible_fund_keys"],
        "tag_any": req["tag_any"],
        "selected_fund_key": req["fund_key"],
        "ops_support_planned": req["ops_support_planned"],
        "actor_rbac_roles": req["actor_rbac_roles"],
        "actor_domain_roles": req["actor_domain_roles"],
    }

    (
        eligible_fund_keys,
        selector_reasons,
        selector_rule_ids,
    ) = _eligible_fund_keys(
        generic_req,
        selectors,
        fund_map,
        profile,
    )

    allowed = True
    reason_codes = [
        f"ops_float_action:{req['action']}",
        f"ops_float_mode:{req['support_mode']}",
        f"source_profile:{profile_key}",
        *selector_reasons,
    ]
    matched_rule_ids = list(selector_rule_ids)

    if req["fund_key"] not in eligible_fund_keys:
        allowed = False
        reason_codes.append("selected_fund_not_eligible_for_destination")
    else:
        reason_codes.append("selected_fund_confirmed")

    approvals, approval_reasons, approval_rule_ids = _approval_requirements(
        generic_req,
        controls,
        profile,
    )
    required_approvals = list(approvals)
    reason_codes.extend(approval_reasons)
    matched_rule_ids.extend(approval_rule_ids)

    if req["action"] == "allocate" and profile.auto_ops_bridge_on_publish:
        reason_codes.append("ops_float_auto_allowed")

    if req["action"] == "forgive":
        if profile.forgiveness_rule == "governor_override_only":
            has_governor = "governor" in req["actor_domain_roles"]
            if not has_governor and "governor" not in required_approvals:
                required_approvals.append("governor")
                reason_codes.append("forgiveness_requires_governor")
            elif has_governor:
                reason_codes.append("forgiveness_governor_present")

    fp_payload = {
        "req": req,
        "source_profile_key": profile_key,
        "allowed": allowed,
        "required_approvals": tuple(required_approvals),
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "selectors_version": int(
            selectors.get("meta", {}).get("version") or 1
        ),
        "controls_version": int(controls.get("meta", {}).get("version") or 1),
    }

    return {
        "allowed": allowed,
        "eligible_fund_keys": eligible_fund_keys,
        "selected_fund_key": req["fund_key"],
        "required_approvals": tuple(required_approvals),
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "decision_fingerprint": _fingerprint(fp_payload),
    }


# for Calendar Project source profile JSON build
def get_funding_source_profile_summary(
    profile_key: str,
) -> FundingSourceProfileSummary:
    if not profile_key or not str(profile_key).strip():
        raise ValueError("source_profile_key is required")

    profile = _get_source_profile_or_raise(str(profile_key).strip())
    if profile is None:
        raise ValueError("source_profile_key is required")

    return FundingSourceProfileSummary(
        key=profile.key,
        source_kind=profile.source_kind,
        support_mode=profile.support_mode,
        approval_posture=profile.approval_posture,
        default_restriction_keys=profile.default_restriction_keys,
        bridge_allowed=profile.bridge_allowed,
        repayment_expectation=profile.repayment_expectation,
        forgiveness_rule=profile.forgiveness_rule,
        auto_ops_bridge_on_publish=profile.auto_ops_bridge_on_publish,
    )
