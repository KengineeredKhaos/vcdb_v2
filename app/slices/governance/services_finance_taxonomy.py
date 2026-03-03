# app/slices/governance/services_finance_taxonomy.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .services_funding_decisions import load_policy_finance_taxonomy


@dataclass(frozen=True)
class KeyLabelDTO:
    key: str
    label: str


@dataclass(frozen=True)
class FundKeyDTO:
    key: str
    label: str
    archetype: str
    default_restriction_keys: tuple[str, ...]


@dataclass(frozen=True)
class FinanceTaxonomyDTO:
    version: int

    fund_keys: tuple[FundKeyDTO, ...]
    restriction_keys: tuple[KeyLabelDTO, ...]
    income_kinds: tuple[KeyLabelDTO, ...]
    expense_kinds: tuple[KeyLabelDTO, ...]
    spending_classes: tuple[KeyLabelDTO, ...]


@dataclass(frozen=True)
class SemanticValidationResultDTO:
    ok: bool
    errors: tuple[str, ...]
    unknown_keys: tuple[str, ...]


# -----------------
# Helpers
# -----------------


def normalize_restriction_keys(
    restriction_keys: tuple[str, ...] = (),
) -> tuple[str, ...]:
    # stable dedupe + sort
    return tuple(sorted({str(k) for k in restriction_keys if str(k)}))


def apply_fund_defaults(
    *,
    fund_key: str,
    restriction_keys: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """
    Returns restriction_keys + fund default restrictions (deduped, sorted).
    """
    fk = get_fund_key(fund_key)
    merged = set(normalize_restriction_keys(restriction_keys))
    merged |= set(fk.default_restriction_keys)
    return tuple(sorted(merged))


def _sorted_keylabels(obj: dict[str, Any]) -> tuple[KeyLabelDTO, ...]:
    out = [
        KeyLabelDTO(key=str(k), label=str(v.get("label") or k))
        for k, v in (obj or {}).items()
    ]
    out.sort(key=lambda x: x.key)
    return tuple(out)


def get_finance_taxonomy() -> FinanceTaxonomyDTO:
    """
    Read-only taxonomy projection for UI dropdowns and validation.
    """
    raw = load_policy_finance_taxonomy()

    funds: list[FundKeyDTO] = []
    for k, v in (raw.get("fund_keys") or {}).items():
        funds.append(
            FundKeyDTO(
                key=str(k),
                label=str(v.get("label") or k),
                archetype=str(v.get("archetype") or "unrestricted"),
                default_restriction_keys=tuple(
                    v.get("default_restriction_keys") or ()
                ),
            )
        )
    funds.sort(key=lambda x: x.key)

    return FinanceTaxonomyDTO(
        version=int(raw.get("version") or 0),
        fund_keys=tuple(funds),
        restriction_keys=_sorted_keylabels(raw.get("restriction_keys") or {}),
        income_kinds=_sorted_keylabels(raw.get("income_kinds") or {}),
        expense_kinds=_sorted_keylabels(raw.get("expense_kinds") or {}),
        spending_classes=_sorted_keylabels(raw.get("spending_classes") or {}),
    )


def _get_map(raw: dict[str, Any], group: str) -> dict[str, Any]:
    return raw.get(group) or {}


def get_fund_key(fund_key: str) -> FundKeyDTO:
    raw = load_policy_finance_taxonomy()
    funds = _get_map(raw, "fund_keys")
    if fund_key not in funds:
        raise LookupError(f"unknown fund_key: {fund_key}")
    v = funds[fund_key] or {}
    return FundKeyDTO(
        key=str(fund_key),
        label=str(v.get("label") or fund_key),
        archetype=str(v.get("archetype") or "unrestricted"),
        default_restriction_keys=tuple(
            v.get("default_restriction_keys") or ()
        ),
    )


def get_taxonomy_label(group: str, key: str) -> KeyLabelDTO:
    """
    group is one of:
      restriction_keys, income_kinds, expense_kinds, spending_classes
    """
    raw = load_policy_finance_taxonomy()
    m = _get_map(raw, group)
    if key not in m:
        raise LookupError(f"unknown {group} key: {key}")
    v = m[key] or {}
    return KeyLabelDTO(key=str(key), label=str(v.get("label") or key))


def validate_semantic_keys(
    *,
    fund_key: str | None = None,
    restriction_keys: tuple[str, ...] = (),
    income_kind: str | None = None,
    expense_kind: str | None = None,
    spending_class: str | None = None,
    demand_eligible_fund_keys: tuple[str, ...] = (),
) -> SemanticValidationResultDTO:
    raw = load_policy_finance_taxonomy()

    unknown: set[str] = set()
    errors: list[str] = []

    def _check(group: str, k: str | None, label: str) -> None:
        if k is None:
            return
        if k not in _get_map(raw, group):
            unknown.add(k)
            errors.append(f"unknown {label}: {k}")

    _check("fund_keys", fund_key, "fund_key")
    _check("income_kinds", income_kind, "income_kind")
    _check("expense_kinds", expense_kind, "expense_kind")
    _check("spending_classes", spending_class, "spending_class")

    known_restr = set(_get_map(raw, "restriction_keys").keys())
    for rk in restriction_keys:
        if rk not in known_restr:
            unknown.add(rk)
            errors.append(f"unknown restriction_key: {rk}")

    known_funds = set(_get_map(raw, "fund_keys").keys())
    for fk in demand_eligible_fund_keys:
        if fk not in known_funds:
            unknown.add(fk)
            errors.append(f"unknown demand_eligible_fund_key: {fk}")

    return SemanticValidationResultDTO(
        ok=(len(errors) == 0),
        errors=tuple(errors),
        unknown_keys=tuple(sorted(unknown)),
    )
