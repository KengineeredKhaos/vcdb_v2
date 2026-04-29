# app/slices/finance/services_dashboard.py

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from app.extensions import db

from .models import (
    Encumbrance,
    FinancePostingFact,
    FinanceQuarantine,
    Journal,
    OpsFloat,
    Reserve,
)


def _as_rows(bucket: dict[str, int]) -> list[dict[str, int | str]]:
    return [
        {"key": key, "amount_cents": int(bucket[key])}
        for key in sorted(bucket.keys())
    ]


def _before_or_equal(value: str | None, as_of_iso: str | None) -> bool:
    if not as_of_iso or not value:
        return True
    return value <= as_of_iso


_SCOPE_PRIORITY = {
    "funding_demand": 0,
    "project": 1,
    "journal": 2,
    "semantic_posting": 3,
    "ops_float": 4,
    "global": 9,
}


def _blocker_priority(row: FinanceQuarantine) -> tuple[int, str, str]:
    return (
        int(_SCOPE_PRIORITY.get(str(row.scope_type), 99)),
        str(row.scope_label or ""),
        str(row.ulid),
    )


def _journal_matches(
    journal_ulid: str,
    *,
    funding_demand_ulid: str,
    project_ulid: str | None,
) -> bool:
    row = db.session.get(Journal, journal_ulid)
    if row is None:
        return False
    if row.funding_demand_ulid == funding_demand_ulid:
        return True
    return bool(project_ulid and row.project_ulid == project_ulid)


def _fact_matches(
    fact_ulid: str,
    *,
    funding_demand_ulid: str,
    project_ulid: str | None,
) -> bool:
    row = db.session.get(FinancePostingFact, fact_ulid)
    if row is None:
        return False
    if row.funding_demand_ulid == funding_demand_ulid:
        return True
    return bool(project_ulid and row.project_ulid == project_ulid)


def _ops_float_matches(
    ops_float_ulid: str,
    *,
    funding_demand_ulid: str,
    project_ulid: str | None,
) -> bool:
    row = db.session.get(OpsFloat, ops_float_ulid)
    if row is None:
        return False

    if row.source_funding_demand_ulid == funding_demand_ulid:
        return True
    if row.dest_funding_demand_ulid == funding_demand_ulid:
        return True

    if project_ulid:
        if row.source_project_ulid == project_ulid:
            return True
        if row.dest_project_ulid == project_ulid:
            return True
    return False


def _quarantine_matches(
    row: FinanceQuarantine,
    *,
    funding_demand_ulid: str,
    project_ulid: str | None,
) -> bool:
    scope_type = str(row.scope_type or "")
    scope_ulid = str(row.scope_ulid or "")

    if scope_type == "global":
        return True
    if scope_type == "funding_demand":
        return scope_ulid == funding_demand_ulid
    if scope_type == "project":
        return bool(project_ulid and scope_ulid == project_ulid)
    if scope_type == "journal":
        return _journal_matches(
            scope_ulid,
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=project_ulid,
        )
    if scope_type == "semantic_posting":
        return _fact_matches(
            scope_ulid,
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=project_ulid,
        )
    if scope_type == "ops_float":
        return _ops_float_matches(
            scope_ulid,
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=project_ulid,
        )
    return False


def get_funding_demand_go_nogo(
    funding_demand_ulid: str,
    *,
    project_ulid: str | None = None,
) -> dict[str, object]:
    """Return blunt Finance integrity gate for staff-facing demand work.

    This read seam answers only whether Finance considers the funding stream
    safe enough for demand processing right now. It does not explain Finance
    internals to staff, and it does not decide whether enough money exists.
    """
    rows = db.session.execute(
        select(FinanceQuarantine).where(FinanceQuarantine.status == "active")
    ).scalars()

    blockers = [
        row
        for row in rows
        if _quarantine_matches(
            row,
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=project_ulid,
        )
    ]
    blockers.sort(key=_blocker_priority)

    if not blockers:
        return {
            "funding_demand_ulid": funding_demand_ulid,
            "project_ulid": project_ulid,
            "go_nogo": "go",
            "escalate_to_admin": False,
            "operator_message": "Finance is clear for demand processing.",
            "blocking_reason_codes": (),
            "blocking_scope_type": None,
            "blocking_scope_ulid": None,
            "blocking_scope_label": None,
        }

    first = blockers[0]
    return {
        "funding_demand_ulid": funding_demand_ulid,
        "project_ulid": project_ulid,
        "go_nogo": "no_go",
        "escalate_to_admin": True,
        "operator_message": (
            "This funding stream is temporarily blocked. Contact Admin."
        ),
        "blocking_reason_codes": tuple(
            sorted({str(row.reason_code) for row in blockers})
        ),
        "blocking_scope_type": first.scope_type,
        "blocking_scope_ulid": first.scope_ulid,
        "blocking_scope_label": first.scope_label,
    }


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
