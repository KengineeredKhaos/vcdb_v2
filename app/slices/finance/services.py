# app/slices/finance/services.py
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import (
    Account,
    BalanceMonthly,
    Fund,
    Journal,
    JournalLine,
    Period,
    Project,
    StatMetric,
)

ALLOWED_TYPES = {"asset", "liability", "net_assets", "revenue", "expense"}
ALLOWED_PERIOD_STATUS = {"open", "soft_closed", "closed"}


# -------- helpers -----------------------------------------------------------


def _period_key_from(ts_iso: str) -> str:
    # "YYYY-MM" from ISO-8601 Z
    # assuming ts like "2025-10-12T19:00:00Z"
    return ts_iso[:7]


def _ensure_open_period(period_key: str) -> None:
    p = db.session.execute(
        select(Period).where(Period.period_key == period_key)
    ).scalar_one_or_none()
    if p is None:
        p = Period(period_key=period_key, status="open")
        db.session.add(p)
        db.session.flush()
    if p.status == "closed":
        raise ValueError(f"period {period_key} is closed")
    # 'soft_closed' is allowed, but your contracts can require
    # an override flag if needed


# -------- reference ensure --------------------------------------------------


def ensure_account(*, code: str, name: str, type: str) -> str:
    type = type.strip().lower()
    if type not in ALLOWED_TYPES:
        raise ValueError("invalid account type")
    a = db.session.execute(
        select(Account).where(Account.code == code)
    ).scalar_one_or_none()
    if a:
        if not a.active:
            a.active = True
            a.name = name
        return a.ulid
    a = Account(code=code, name=name, type=type, active=True)
    db.session.add(a)
    db.session.commit()
    return a.ulid


def ensure_fund(*, code: str, name: str, restriction: str) -> str:
    restriction = {
        "unrestricted": "unrestricted",
        "temp": "temp",
        "permanent": "perm",
    }.get(restriction, restriction)
    if restriction not in {"unrestricted", "temp", "perm"}:
        raise ValueError("invalid restriction")
    f = db.session.execute(
        select(Fund).where(Fund.code == code)
    ).scalar_one_or_none()
    if f:
        if not f.active:
            f.active = True
            f.name = name
            f.restriction = restriction
        return f.ulid
    f = Fund(code=code, name=name, restriction=restriction, active=True)
    db.session.add(f)
    db.session.commit()
    return f.ulid


def ensure_project(*, name: str) -> str:
    p = Project(name=name, active=True)
    db.session.add(p)
    db.session.commit()
    return p.ulid


# -------- journals ----------------------------------------------------------


def post_journal(
    *,
    source: str,
    external_ref_ulid: Optional[str],
    happened_at_utc: str,
    currency: str,
    memo: Optional[str],
    lines: list[dict],
    created_by_actor: Optional[str],
) -> str:
    """Validate and post a balanced USD journal."""
    if (currency or "").upper() != "USD":
        raise ValueError("only USD supported")
    period_key = _period_key_from(happened_at_utc)
    _ensure_open_period(period_key)

    if not lines or len(lines) < 2:
        raise ValueError("journal requires at least two lines")

    # pre-validate refs
    acct_codes = {l["account_code"] for l in lines}
    fund_codes = {l["fund_code"] for l in lines}
    found_accts = {
        r.code
        for r in db.session.execute(
            select(Account).where(Account.code.in_(list(acct_codes)))
        ).scalars()
    }
    if acct_codes - found_accts:
        raise ValueError(
            f"unknown accounts: {sorted(acct_codes - found_accts)}"
        )
    found_funds = {
        r.code
        for r in db.session.execute(
            select(Fund).where(Fund.code.in_(list(fund_codes)))
        ).scalars()
    }
    if fund_codes - found_funds:
        raise ValueError(f"unknown funds: {sorted(fund_codes - found_funds)}")

    # balance check
    total = sum(int(l["amount_cents"]) for l in lines)
    if total != 0:
        raise ValueError("journal not balanced (sum != 0)")

    j = Journal(
        source=source,
        external_ref_ulid=external_ref_ulid,
        currency="USD",
        period_key=period_key,
        happened_at_utc=happened_at_utc,
        memo=(memo or None),
        created_by_actor=created_by_actor,
        posted_at_utc=now_iso8601_ms(),
    )
    db.session.add(j)
    db.session.flush()  # to get j.ulid

    seq = 1
    for l in lines:
        db.session.add(
            JournalLine(
                journal_ulid=j.ulid,
                seq=seq,
                account_code=l["account_code"],
                fund_code=l["fund_code"],
                project_ulid=l.get("project_ulid"),
                amount_cents=int(l["amount_cents"]),
                memo=(l.get("memo") or None),
                period_key=period_key,
            )
        )
        seq += 1

    # update balances projection incrementally
    _apply_to_balances(lines=lines, period_key=period_key)

    db.session.commit()

    event_bus.emit(
        domain="finance",
        operation="journal.posted",
        request_id=j.ulid,
        actor_ulid=created_by_actor,
        target_ulid=j.ulid,
        happened_at_utc=j.posted_at_utc,
        refs={"lines_count": len(lines), "period_key": period_key},
        chain_key="finance.journal",
    )
    return j.ulid


def reverse_journal(
    *, journal_ulid: str, created_by_actor: Optional[str]
) -> str:
    """Create an exact reversal of an existing journal."""
    j = db.session.get(Journal, journal_ulid)
    if not j:
        raise ValueError("journal not found")
    _ensure_open_period(j.period_key)

    orig_lines = (
        db.session.execute(
            select(JournalLine)
            .where(JournalLine.journal_ulid == j.ulid)
            .order_by(JournalLine.seq)
        )
        .scalars()
        .all()
    )
    lines = []
    for l in orig_lines:
        lines.append(
            {
                "account_code": l.account_code,
                "fund_code": l.fund_code,
                "project_ulid": l.project_ulid,
                "amount_cents": -l.amount_cents,  # reverse
                "memo": f"Reversal of {j.ulid}",
            }
        )

    return post_journal(
        source="finance",
        external_ref_ulid=j.ulid,
        happened_at_utc=now_iso8601_ms(),
        currency=j.currency,
        memo=f"Reversal of {j.ulid}",
        lines=lines,
        created_by_actor=created_by_actor,
    )


# -------- inkind & restrictions (policy-aware) ------------------------------


def record_inkind(
    *,
    happened_at_utc: str,
    fund_code: str,
    amount_cents: int,
    expense_acct: str = "5200",
    revenue_acct: str = "4200",
    memo: Optional[str],
    external_ref_ulid: Optional[str],
    created_by_actor: Optional[str],
    valuation_basis: str,
) -> str:
    """
    Record in-kind with reliable valuation.
    DRMO 'no fair value' SHOULD NOT call this.
    """
    if amount_cents is None or int(amount_cents) <= 0:
        raise ValueError("amount_cents must be > 0")
    # Minimal validation that valuation_basis token is present;
    # Governance can define allowed tokens later.
    if not valuation_basis or not str(valuation_basis).strip():
        raise ValueError("valuation_basis required")

    lines = [
        {
            "account_code": expense_acct,
            "fund_code": fund_code,
            "amount_cents": int(amount_cents),
            "memo": memo,
        },
        {
            "account_code": revenue_acct,
            "fund_code": fund_code,
            "amount_cents": -int(amount_cents),
            "memo": memo,
        },
    ]
    return post_journal(
        source="finance",
        external_ref_ulid=external_ref_ulid,
        happened_at_utc=happened_at_utc,
        currency="USD",
        memo=(memo or f"in-kind ({valuation_basis})"),
        lines=lines,
        created_by_actor=created_by_actor,
    )


def release_restriction(
    *,
    happened_at_utc: str,
    amount_cents: int,
    restricted_fund: str,
    unrestricted_fund: str = "unrestricted",
    net_assets_with_restr_acct: str = "3100",
    net_assets_without_restr_acct: str = "3000",
    memo: Optional[str],
    created_by_actor: Optional[str],
) -> str:
    """
    Move net assets from restricted -> unrestricted (names-only).
    """
    if int(amount_cents) <= 0:
        raise ValueError("amount_cents must be > 0")

    lines = [
        # Decrease NA with restriction (debit)
        {
            "account_code": net_assets_with_restr_acct,
            "fund_code": restricted_fund,
            "amount_cents": int(amount_cents),
            "memo": memo,
        },
        # Increase NA without restriction (credit)
        {
            "account_code": net_assets_without_restr_acct,
            "fund_code": unrestricted_fund,
            "amount_cents": -int(amount_cents),
            "memo": memo,
        },
    ]
    return post_journal(
        source="finance",
        external_ref_ulid=None,
        happened_at_utc=happened_at_utc,
        currency="USD",
        memo=memo or "Release from restriction",
        lines=lines,
        created_by_actor=created_by_actor,
    )


# -------- balances projection -----------------------------------------------


def _apply_to_balances(*, lines: Iterable[dict], period_key: str) -> None:
    buckets: dict[tuple[str, str, Optional[str]], int] = defaultdict(int)
    for l in lines:
        k = (l["account_code"], l["fund_code"], l.get("project_ulid"))
        buckets[k] += int(l["amount_cents"])

    now = now_iso8601_ms()
    for (acct, fund, project), net in buckets.items():
        row = db.session.execute(
            select(BalanceMonthly).where(
                BalanceMonthly.account_code == acct,
                BalanceMonthly.fund_code == fund,
                BalanceMonthly.project_ulid.is_(project)
                if project is None
                else BalanceMonthly.project_ulid == project,
                BalanceMonthly.period_key == period_key,
            )
        ).scalar_one_or_none()
        if not row:
            row = BalanceMonthly(
                account_code=acct,
                fund_code=fund,
                project_ulid=project,
                period_key=period_key,
                debits_cents=0,
                credits_cents=0,
                net_cents=0,
            )
            db.session.add(row)
        # + is debit, - is credit by convention
        if net >= 0:
            row.debits_cents += net
        else:
            row.credits_cents += -net
        row.net_cents += net
        row.updated_at_utc = now


def rebuild_balances(*, period_from: str, period_to: str) -> dict:
    """
    Recompute balances from scratch for [period_from, period_to], inclusive.
    """
    # wipe range
    db.session.query(BalanceMonthly).filter(
        BalanceMonthly.period_key >= period_from,
        BalanceMonthly.period_key <= period_to,
    ).delete()

    # gather lines in range
    lines = (
        db.session.execute(
            select(JournalLine).where(
                JournalLine.period_key >= period_from,
                JournalLine.period_key <= period_to,
            )
        )
        .scalars()
        .all()
    )
    buckets: dict[str, list[dict]] = defaultdict(list)
    for l in lines:
        buckets[l.period_key].append(
            {
                "account_code": l.account_code,
                "fund_code": l.fund_code,
                "project_ulid": l.project_ulid,
                "amount_cents": l.amount_cents,
            }
        )
    for pk, bunch in buckets.items():
        _apply_to_balances(lines=bunch, period_key=pk)

    db.session.commit()
    event_bus.emit(
        domain="finance",
        operation="balance.rebuild",
        request_id="-",
        actor_ulid=None,
        target_ulid="-",
        happened_at_utc=now_iso8601_ms(),
        refs={
            "period_from": period_from,
            "period_to": period_to,
            "rows": len(lines),
        },
        chain_key="finance.balance",
    )
    return {"rows": len(lines), "periods": len(buckets)}


# -------- periods -----------------------------------------------------------


def set_period_status(*, period_key: str, status: str) -> None:
    status = status.strip().lower()
    if status not in ALLOWED_PERIOD_STATUS:
        raise ValueError("invalid period status")
    p = db.session.execute(
        select(Period).where(Period.period_key == period_key)
    ).scalar_one_or_none()
    if not p:
        p = Period(period_key=period_key, status=status)
        db.session.add(p)
    else:
        p.status = status
    db.session.commit()
    event_bus.emit(
        domain="finance",
        operation="period.status_changed",
        request_id="-",
        actor_ulid=None,
        target_ulid=period_key,
        happened_at_utc=now_iso8601_ms(),
        refs={"status": status},
        chain_key="finance.period",
    )


# -------- statistical metrics (DRMO non-monetary) ---------------------------


def record_stat_metric(
    *,
    period_key: str,
    metric_code: str,
    quantity: int,
    unit: str,
    source: str,
    source_ref_ulid: Optional[str],
) -> str:
    """
    Off-GL non-monetary snapshot (e.g., STAT_FOOD_LBS). Use from Logistics.
    """
    if quantity < 0:
        raise ValueError("quantity must be >= 0")
    m = StatMetric(
        period_key=period_key,
        metric_code=metric_code,
        quantity=int(quantity),
        unit=unit,
        source=source,
        source_ref_ulid=source_ref_ulid,
    )
    db.session.add(m)
    db.session.commit()
    event_bus.emit(
        domain="finance",
        operation="stat.recorded",
        request_id="-",
        actor_ulid=None,
        target_ulid=m.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "period_key": period_key,
            "metric_code": metric_code,
            "quantity": quantity,
        },
        chain_key="finance.stat",
    )

    return m.ulid
