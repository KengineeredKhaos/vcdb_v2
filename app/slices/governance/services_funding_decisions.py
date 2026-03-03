# app/slices/governance/services_funding_decisions.py

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


_ALLOWED_OPS: set[str] = {"reserve", "encumber", "spend", "receive"}


def _data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_policy_finance_taxonomy() -> dict[str, Any]:
    return _load_json(_data_dir() / "policy_finance_taxonomy.json")


@lru_cache(maxsize=1)
def load_policy_finance_selectors() -> dict[str, Any]:
    return _load_json(_data_dir() / "policy_finance_selectors.json")


@lru_cache(maxsize=1)
def load_policy_finance_controls() -> dict[str, Any]:
    return _load_json(_data_dir() / "policy_finance_controls.json")


def _stable_dumps(obj: Any) -> str:
    """
    Prefer app.lib.jsonutil.stable_dumps if you want perfect consistency
    across the app; this minimal fallback is good enough for a fingerprint.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _as_tuple(x: Any) -> tuple[Any, ...]:
    if x is None:
        return ()
    if isinstance(x, tuple):
        return x
    if isinstance(x, list):
        return tuple(x)
    return (x,)


def _set(x: Any) -> set[str]:
    return {str(v) for v in _as_tuple(x)}


def _has_any(hay: set[str], needles: Iterable[str]) -> bool:
    for n in needles:
        if n in hay:
            return True
    return False


def _has_all(hay: set[str], needles: Iterable[str]) -> bool:
    for n in needles:
        if n not in hay:
            return False
    return True


def _match_common(
    match: dict[str, Any],
    *,
    op: str,
    amount_cents: int,
    spending_class: str | None,
    income_kind: str | None,
    expense_kind: str | None,
    restriction_keys: set[str],
    tag_any: set[str],
) -> bool:
    ops = _set(match.get("op"))
    if ops and op not in ops:
        return False

    gte = match.get("amount_cents_gte")
    if gte is not None and amount_cents < int(gte):
        return False

    lte = match.get("amount_cents_lte")
    if lte is not None and amount_cents > int(lte):
        return False

    gt = match.get("amount_cents_gt")
    if gt is not None and amount_cents <= int(gt):
        return False

    sc = _set(match.get("spending_class"))
    if sc and (spending_class is None or spending_class not in sc):
        return False

    ik = _set(match.get("income_kind"))
    if ik and (income_kind is None or income_kind not in ik):
        return False

    ek = _set(match.get("expense_kind"))
    if ek and (expense_kind is None or expense_kind not in ek):
        return False

    any_keys = _set(match.get("restriction_keys_any"))
    if any_keys and not _has_any(restriction_keys, any_keys):
        return False

    all_keys = _set(match.get("restriction_keys_all"))
    if all_keys and not _has_all(restriction_keys, all_keys):
        return False

    tags = _set(match.get("tag_any"))
    if tags and not _has_any(tag_any, tags):
        return False

    return True


def _validate_req_against_taxonomy(
    tax: dict[str, Any],
    req: dict[str, Any],
) -> None:
    def _must_exist(group: str, key: str | None, field: str) -> None:
        if key is None:
            return
        if key not in tax.get(group, {}):
            raise ValueError(f"unknown {field}: {key}")

    _must_exist(
        "spending_classes", req.get("spending_class"), "spending_class"
    )
    _must_exist("income_kinds", req.get("income_kind"), "income_kind")
    _must_exist("expense_kinds", req.get("expense_kind"), "expense_kind")

    rkeys = _set(req.get("restriction_keys"))
    known_r = set(tax.get("restriction_keys", {}).keys())
    unknown = sorted([k for k in rkeys if k not in known_r])
    if unknown:
        raise ValueError(f"unknown restriction_keys: {unknown}")

    demand_funds = _set(req.get("demand_eligible_fund_keys"))
    known_funds = set(tax.get("fund_keys", {}).keys())
    bad_funds = sorted([k for k in demand_funds if k not in known_funds])
    if bad_funds:
        raise ValueError(f"unknown demand_eligible_fund_keys: {bad_funds}")

    sel = req.get("selected_fund_key")
    if sel is not None and str(sel) not in known_funds:
        raise ValueError(f"unknown selected_fund_key: {sel}")


def _compute_eligible_funds(
    tax: dict[str, Any],
    selectors: dict[str, Any],
    req: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    Returns (eligible_fund_keys, matched_selector_rule_ids).
    """
    op = str(req["op"])
    amount_cents = int(req["amount_cents"])
    spending_class = req.get("spending_class")
    income_kind = req.get("income_kind")
    expense_kind = req.get("expense_kind")
    restriction_keys = _set(req.get("restriction_keys"))
    tag_any = _set(req.get("tag_any"))

    rules = list(selectors.get("rules") or [])
    rules.sort(key=lambda r: int(r.get("priority") or 0), reverse=True)

    matched_ids: list[str] = []
    allow_set: set[str] = set()
    prefer_seq: list[str] = []

    for r in rules:
        match = r.get("match") or {}
        if not _match_common(
            match,
            op=op,
            amount_cents=amount_cents,
            spending_class=spending_class,
            income_kind=income_kind,
            expense_kind=expense_kind,
            restriction_keys=restriction_keys,
            tag_any=tag_any,
        ):
            continue

        rid = str(r.get("rule_id") or "")
        if rid:
            matched_ids.append(rid)

        allow = _set(r.get("allow_fund_keys"))
        allow_set |= allow

        prefer = [str(x) for x in _as_tuple(r.get("prefer_fund_keys"))]
        for k in prefer:
            if k in allow_set and k not in prefer_seq:
                prefer_seq.append(k)

    # Build stable, ordered eligible list:
    remaining = sorted([k for k in allow_set if k not in set(prefer_seq)])
    eligible = tuple(prefer_seq + remaining)

    demand_eligible = _set(req.get("demand_eligible_fund_keys"))
    if demand_eligible:
        eligible = tuple([k for k in eligible if k in demand_eligible])

    return eligible, tuple(matched_ids)


def _fund_archetype_for(
    tax: dict[str, Any],
    fund_key: str,
) -> str | None:
    f = (tax.get("fund_keys") or {}).get(fund_key) or {}
    a = f.get("archetype")
    return str(a) if a else None


def _match_controls(
    match: dict[str, Any],
    *,
    tax: dict[str, Any],
    op: str,
    amount_cents: int,
    spending_class: str | None,
    income_kind: str | None,
    expense_kind: str | None,
    restriction_keys: set[str],
    selected_fund_key: str | None,
) -> bool:
    if not _match_common(
        match,
        op=op,
        amount_cents=amount_cents,
        spending_class=spending_class,
        income_kind=income_kind,
        expense_kind=expense_kind,
        restriction_keys=restriction_keys,
        tag_any=set(),
    ):
        return False

    fk_any = _set(match.get("fund_key_any"))
    if fk_any:
        if selected_fund_key is None or selected_fund_key not in fk_any:
            return False

    fa_any = _set(match.get("fund_archetype_any"))
    if fa_any:
        if selected_fund_key is None:
            return False
        a = _fund_archetype_for(tax, selected_fund_key)
        if a is None or a not in fa_any:
            return False

    return True


def preview_funding_decision(req: dict[str, Any]) -> dict[str, Any]:
    """
    Pure governance evaluator for funding semantics and approval rules.

    Input (req) is a plain dict to avoid slices importing contracts.
    Expected keys:
      op, amount_cents,
      spending_class?, income_kind?, expense_kind?,
      restriction_keys?, demand_eligible_fund_keys?, tag_any?,
      funding_demand_ulid?, project_ulid?,
      selected_fund_key?, actor_rbac_roles?, actor_domain_roles?

    Output keys:
      allowed, eligible_fund_keys, selected_fund_key,
      required_approvals, reason_codes, matched_rule_ids,
      decision_fingerprint
    """
    tax = load_policy_finance_taxonomy()
    selectors = load_policy_finance_selectors()
    controls = load_policy_finance_controls()

    op = str(req.get("op") or "")
    if op not in _ALLOWED_OPS:
        raise ValueError(f"bad op: {op}")

    amount_cents = int(req.get("amount_cents") or 0)
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")

    req2 = dict(req)
    req2["op"] = op
    req2["amount_cents"] = amount_cents

    # Normalize list-y inputs
    req2["restriction_keys"] = tuple(_set(req2.get("restriction_keys")))
    req2["demand_eligible_fund_keys"] = tuple(
        _set(req2.get("demand_eligible_fund_keys"))
    )
    req2["tag_any"] = tuple(_set(req2.get("tag_any")))
    if req2.get("selected_fund_key") is not None:
        req2["selected_fund_key"] = str(req2["selected_fund_key"])

    _validate_req_against_taxonomy(tax, req2)

    eligible, sel_rule_ids = _compute_eligible_funds(tax, selectors, req2)

    allowed = True
    required_approvals: set[str] = set()
    reason_codes: list[str] = []
    matched_rule_ids: list[str] = list(sel_rule_ids)

    selected_fund_key = req2.get("selected_fund_key")
    if selected_fund_key is not None and selected_fund_key not in eligible:
        allowed = False
        reason_codes.append("selected_fund_not_eligible")

    # Controls are evaluated only when a fund key is selected.
    # This keeps "preview eligible funds" separate from "approve spend".
    rules = list((controls.get("approval_rules") or []))
    rules.sort(key=lambda r: int(r.get("priority") or 0), reverse=True)

    spending_class = req2.get("spending_class")
    income_kind = req2.get("income_kind")
    expense_kind = req2.get("expense_kind")
    restriction_keys = _set(req2.get("restriction_keys"))

    if selected_fund_key is not None:
        for r in rules:
            match = r.get("match") or {}
            if not _match_controls(
                match,
                tax=tax,
                op=op,
                amount_cents=amount_cents,
                spending_class=spending_class,
                income_kind=income_kind,
                expense_kind=expense_kind,
                restriction_keys=restriction_keys,
                selected_fund_key=selected_fund_key,
            ):
                continue

            rid = str(r.get("rule_id") or "")
            if rid:
                matched_rule_ids.append(rid)

            rc = r.get("reason_code")
            if rc:
                reason_codes.append(str(rc))

            req_appr = _set(r.get("required_approvals"))
            required_approvals |= req_appr

            if bool(r.get("deny")):
                allowed = False
                if rc is None:
                    reason_codes.append("denied_by_policy")
                break

    # Deterministic fingerprint for traceability.
    fingerprint_payload = {
        "op": op,
        "amount_cents": amount_cents,
        "funding_demand_ulid": req2.get("funding_demand_ulid"),
        "project_ulid": req2.get("project_ulid"),
        "spending_class": spending_class,
        "income_kind": income_kind,
        "expense_kind": expense_kind,
        "restriction_keys": req2["restriction_keys"],
        "demand_eligible_fund_keys": req2["demand_eligible_fund_keys"],
        "tag_any": req2["tag_any"],
        "selected_fund_key": selected_fund_key,
        "matched_rule_ids": tuple(matched_rule_ids),
        "required_approvals": tuple(sorted(required_approvals)),
        "allowed": allowed,
    }
    decision_fingerprint = _sha256_hex(_stable_dumps(fingerprint_payload))

    return {
        "allowed": allowed,
        "eligible_fund_keys": eligible,
        "selected_fund_key": selected_fund_key,
        "required_approvals": tuple(sorted(required_approvals)),
        "reason_codes": tuple(reason_codes),
        "matched_rule_ids": tuple(matched_rule_ids),
        "decision_fingerprint": decision_fingerprint,
    }
