# app/slices/finance/services_dashboard.py

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from app.extensions import db

from .models import Encumbrance, FinancePostingFact, Reserve


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

    fact_rows = db.session.execute(
        select(FinancePostingFact).where(
            FinancePostingFact.funding_demand_ulid == funding_demand_ulid
        )
    ).scalars()
    for row in fact_rows:
        if not _before_or_equal(row.happened_at_utc, as_of_iso):
            continue
        amount = int(row.amount_cents or 0)
        if row.posting_family == "income":
            received_cents += amount
            received_by_fund[str(row.fund_code)] += amount
            income_by_income_kind[str(row.semantic_key)] += amount
            income_journal_ulids.add(str(row.journal_ulid))
        elif row.posting_family == "expense":
            spent_cents += amount
            spent_by_expense_kind[str(row.semantic_key)] += amount
            expense_journal_ulids.add(str(row.journal_ulid))

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
        amount = int(row.amount_cents or 0)
        reserved_cents += amount
        reserved_by_fund[str(row.fund_code)] += amount

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
        "fund_code": row.fund_code,
        "amount_cents": int(row.amount_cents or 0),
        "relieved_cents": int(row.relieved_cents or 0),
        "open_cents": open_cents,
        "status": row.status,
        "decision_fingerprint": row.decision_fingerprint,
        "source_ref_ulid": row.source_ref_ulid,
    }
