# app/slices/finance/services_posting_map.py

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

# NOTE: COA currently lives in services_journal. Keeping this import cheap
# for now; later you may want to move COA to a finance/coa.py module.
from .services_journal import COA


@dataclass(frozen=True)
class PostingMap:
    version: int
    receipt_method_debit_account: dict[str, str]
    payment_method_credit_account: dict[str, str]
    income_kind_credit_account: dict[str, str]
    expense_kind_debit_account: dict[str, str]


def _data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_posting_map_v1() -> PostingMap:
    raw = _load_json(_data_dir() / "posting_map_v1.json")
    pm = PostingMap(
        version=int(raw.get("version") or 0),
        receipt_method_debit_account=dict(
            raw.get("receipt_method_debit_account") or {}
        ),
        payment_method_credit_account=dict(
            raw.get("payment_method_credit_account") or {}
        ),
        income_kind_credit_account=dict(
            raw.get("income_kind_credit_account") or {}
        ),
        expense_kind_debit_account=dict(
            raw.get("expense_kind_debit_account") or {}
        ),
    )
    validate_posting_map(pm)
    return pm


def _coa_spec(coa_key: str) -> dict[str, str]:
    try:
        return COA[coa_key]
    except KeyError as exc:
        raise LookupError(f"unknown COA key: {coa_key}") from exc


def resolve_account_code(coa_key: str) -> str:
    return _coa_spec(coa_key)["code"]


def _require_coa_type(coa_key: str, allowed: set[str]) -> None:
    spec = _coa_spec(coa_key)
    t = (spec.get("type") or "").strip()
    if t not in allowed:
        raise ValueError(
            f"COA key {coa_key!r} has type {t!r}; expected {sorted(allowed)}"
        )


def validate_posting_map(pm: PostingMap) -> None:
    """
    Validation is Finance-local:
    - referenced COA keys must exist
    - referenced COA keys must be plausible types

    We intentionally do NOT import Governance here. A separate CLI/health
    check can validate "coverage vs Governance taxonomy" later.
    """
    # receipt method debits should be assets (cash-like)
    for method, coa_key in pm.receipt_method_debit_account.items():
        if not method:
            raise ValueError("empty receipt method key")
        _require_coa_type(coa_key, {"asset"})

    # payment method credits can be asset or liability
    for method, coa_key in pm.payment_method_credit_account.items():
        if not method:
            raise ValueError("empty payment method key")
        _require_coa_type(coa_key, {"asset", "liability"})

    # income credits should be revenue
    for kind, coa_key in pm.income_kind_credit_account.items():
        if not kind:
            raise ValueError("empty income_kind key")
        _require_coa_type(coa_key, {"revenue"})

    # expense debits should be expense
    for kind, coa_key in pm.expense_kind_debit_account.items():
        if not kind:
            raise ValueError("empty expense_kind key")
        _require_coa_type(coa_key, {"expense"})


def select_income_account_codes(
    *,
    income_kind: str,
    receipt_method: str,
) -> tuple[str, str]:
    pm = load_posting_map_v1()

    try:
        debit_key = pm.receipt_method_debit_account[receipt_method]
    except KeyError as exc:
        raise ValueError(
            f"unknown receipt_method: {receipt_method!r}"
        ) from exc

    try:
        credit_key = pm.income_kind_credit_account[income_kind]
    except KeyError as exc:
        raise ValueError(f"unknown income_kind: {income_kind!r}") from exc

    return resolve_account_code(debit_key), resolve_account_code(credit_key)


def select_expense_account_codes(
    *,
    expense_kind: str,
    payment_method: str,
) -> tuple[str, str]:
    pm = load_posting_map_v1()

    try:
        debit_key = pm.expense_kind_debit_account[expense_kind]
    except KeyError as exc:
        raise ValueError(f"unknown expense_kind: {expense_kind!r}") from exc

    try:
        credit_key = pm.payment_method_credit_account[payment_method]
    except KeyError as exc:
        raise ValueError(
            f"unknown payment_method: {payment_method!r}"
        ) from exc

    return resolve_account_code(debit_key), resolve_account_code(credit_key)
