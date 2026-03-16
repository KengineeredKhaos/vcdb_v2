# app/slices/finance/services_dashboard.py

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select

from app.extensions import db
from app.slices.finance.models import Encumbrance, Reserve
from app.slices.ledger.models import LedgerEvent


def _load_json(text: str | None) -> dict:
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except Exception:  # noqa: BLE001
        return {}
    return raw if isinstance(raw, dict) else {}


def _as_rows(bucket: dict[str, int]) -> list[dict[str, int | str]]:
    return [
        {"key": key, "amount_cents": int(bucket[key])}
        for key in sorted(bucket.keys())
    ]


def _before_or_equal(value: str | None, as_of_iso: str | None) -> bool:
    if not as_of_iso or not value:
        return True
    return value <= as_of_iso


def get_funding_demand_money_view(
    funding_demand_ulid: str,
    *,
    as_of_iso: str | None = None,
) -> dict[str, object]:
    received_by_fund: dict[str, int] = defaultdict(int)
    reserved_by_fund: dict[str, int] = defaultdict(int)
    encumbered_by_fund: dict[str, int] = defaultdict(int)
    spent_by_expense_kind: dict[str, int] = defaultdict(int)
    income_by_income_kind: dict[str, int] = defaultdict(int)

    income_journal_ulids: set[str] = set()
    expense_journal_ulids: set[str] = set()
    reserve_ulids: set[str] = set()
    encumbrance_ulids: set[str] = set()

    received_cents = 0
    reserved_cents = 0
    encumbered_cents = 0
    spent_cents = 0

    income_rows = db.session.execute(
        select(LedgerEvent).where(
            LedgerEvent.event_type == "finance.income_posted"
        )
    ).scalars()
    for row in income_rows:
        if not _before_or_equal(row.happened_at_utc, as_of_iso):
            continue
        refs = _load_json(row.refs_json)
        if refs.get("funding_demand_ulid") != funding_demand_ulid:
            continue
        amount = int(refs.get("amount_cents") or 0)
        fund_key = str(refs.get("fund_key") or "")
        income_kind = str(refs.get("income_kind") or "")

        received_cents += amount
        if fund_key:
            received_by_fund[fund_key] += amount
        if income_kind:
            income_by_income_kind[income_kind] += amount
        if row.target_ulid:
            income_journal_ulids.add(str(row.target_ulid))

    expense_rows = db.session.execute(
        select(LedgerEvent).where(
            LedgerEvent.event_type == "finance.expense_posted"
        )
    ).scalars()
    for row in expense_rows:
        if not _before_or_equal(row.happened_at_utc, as_of_iso):
            continue
        refs = _load_json(row.refs_json)
        if refs.get("funding_demand_ulid") != funding_demand_ulid:
            continue
        amount = int(refs.get("amount_cents") or 0)
        expense_kind = str(refs.get("expense_kind") or "")

        spent_cents += amount
        if expense_kind:
            spent_by_expense_kind[expense_kind] += amount
        if row.target_ulid:
            expense_journal_ulids.add(str(row.target_ulid))

    reserve_rows = db.session.execute(
        select(Reserve).where(
            Reserve.funding_demand_ulid == funding_demand_ulid
        )
    ).scalars()
    for row in reserve_rows:
        if not _before_or_equal(row.created_at_utc, as_of_iso):
            continue
        reserve_ulids.add(row.ulid)
        if row.status != "active":
            continue
        reserved_cents += int(row.amount_cents or 0)
        reserved_by_fund[str(row.fund_code)] += int(row.amount_cents or 0)

    enc_rows = db.session.execute(
        select(Encumbrance).where(
            Encumbrance.funding_demand_ulid == funding_demand_ulid
        )
    ).scalars()
    for row in enc_rows:
        if not _before_or_equal(row.created_at_utc, as_of_iso):
            continue
        encumbrance_ulids.add(row.ulid)
        if row.status == "void":
            continue
        open_cents = max(
            int(row.amount_cents or 0) - int(row.relieved_cents or 0),
            0,
        )
        encumbered_cents += open_cents
        if open_cents:
            encumbered_by_fund[str(row.fund_code)] += open_cents

    return {
        "funding_demand_ulid": funding_demand_ulid,
        "received_cents": received_cents,
        "reserved_cents": reserved_cents,
        "encumbered_cents": encumbered_cents,
        "spent_cents": spent_cents,
        "received_by_fund": _as_rows(received_by_fund),
        "reserved_by_fund": _as_rows(reserved_by_fund),
        "encumbered_by_fund": _as_rows(encumbered_by_fund),
        "spent_by_expense_kind": _as_rows(spent_by_expense_kind),
        "income_by_income_kind": _as_rows(income_by_income_kind),
        "income_journal_ulids": sorted(income_journal_ulids),
        "expense_journal_ulids": sorted(expense_journal_ulids),
        "reserve_ulids": sorted(reserve_ulids),
        "encumbrance_ulids": sorted(encumbrance_ulids),
    }


def get_encumbrance_view(encumbrance_ulid: str) -> dict[str, object]:
    row = db.session.get(Encumbrance, encumbrance_ulid)
    if row is None:
        raise LookupError(f"encumbrance not found: {encumbrance_ulid}")

    open_cents = max(
        int(row.amount_cents or 0) - int(row.relieved_cents or 0),
        0,
    )
    return {
        "encumbrance_ulid": row.ulid,
        "funding_demand_ulid": row.funding_demand_ulid,
        "project_ulid": row.project_ulid,
        "fund_key": row.fund_code,
        "amount_cents": int(row.amount_cents or 0),
        "relieved_cents": int(row.relieved_cents or 0),
        "open_cents": open_cents,
        "status": row.status,
        "source_ref_ulid": row.source_ref_ulid,
    }
