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
class FinanceTaxonomy:
    version: int

    fund_codes: tuple[FundKeyDTO, ...]
    restriction_keys: tuple[KeyLabelDTO, ...]
    income_kinds: tuple[KeyLabelDTO, ...]
    expense_kinds: tuple[KeyLabelDTO, ...]
    spending_classes: tuple[KeyLabelDTO, ...]


@dataclass(frozen=True)
class SemanticValidationResult:
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
    fund_code: str,
    restriction_keys: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """
    Returns restriction_keys + fund default restrictions (deduped, sorted).
    """
    fk = get_fund_code(fund_code)
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


def get_finance_taxonomy() -> FinanceTaxonomy:
    """
    Read-only taxonomy projection for UI dropdowns and validation.
    """
    raw = load_policy_finance_taxonomy()

    funds: list[FundKeyDTO] = []
    for k, v in (raw.get("fund_codes") or {}).items():
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

    return FinanceTaxonomy(
        version=int(raw.get("version") or 0),
        fund_codes=tuple(funds),
        restriction_keys=_sorted_keylabels(raw.get("restriction_keys") or {}),
        income_kinds=_sorted_keylabels(raw.get("income_kinds") or {}),
        expense_kinds=_sorted_keylabels(raw.get("expense_kinds") or {}),
        spending_classes=_sorted_keylabels(raw.get("spending_classes") or {}),
    )


def _get_map(raw: dict[str, Any], group: str) -> dict[str, Any]:
    return raw.get(group) or {}


def get_fund_code(fund_code: str) -> FundKeyDTO:
    raw = load_policy_finance_taxonomy()
    funds = _get_map(raw, "fund_codes")
    if fund_code not in funds:
        raise LookupError(f"unknown fund_code: {fund_code}")
    v = funds[fund_code] or {}
    return FundKeyDTO(
        key=str(fund_code),
        label=str(v.get("label") or fund_code),
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
    fund_code: str | None = None,
    restriction_keys: tuple[str, ...] = (),
    income_kind: str | None = None,
    expense_kind: str | None = None,
    spending_classes: str | None = None,
    demand_eligible_fund_codes: tuple[str, ...] = (),
) -> SemanticValidationResult:
    raw = load_policy_finance_taxonomy()

    errors: list[str] = []
    unknown_keys: list[str] = []

    def _check_one(policy_group: str, value: str | None, label: str) -> None:
        if value is None:
            return
        allowed = _get_map(raw, policy_group)
        if value not in allowed:
            errors.append(f"unknown {label}: {value}")
            unknown_keys.append(value)

    def _check_many(
        policy_group: str,
        values: tuple[str, ...],
        label: str,
    ) -> None:
        allowed = _get_map(raw, policy_group)
        for value in values:
            if value not in allowed:
                errors.append(f"unknown {label}: {value}")
                unknown_keys.append(value)

    _check_one("fund_codes", fund_code, "fund_code")
    _check_many("restriction_keys", restriction_keys, "restriction_key")
    _check_one("income_kinds", income_kind, "income_kind")
    _check_one("expense_kinds", expense_kind, "expense_kind")
    _check_one("spending_classes", spending_classes, "spending_classes")
    _check_many(
        "fund_codes",
        demand_eligible_fund_codes,
        "demand_eligible_fund_code",
    )

    return SemanticValidationResult(
        ok=not errors,
        errors=tuple(errors),
        unknown_keys=tuple(unknown_keys),
    )
