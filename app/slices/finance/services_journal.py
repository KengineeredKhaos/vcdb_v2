# app/slices/finance/services_journal.py
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts.finance_v2 import (
    ActivitiesReportDTO,
    BudgetDTO,
    DonationDTO,
    ExpenseDTO,
    FundDTO,
    GrantDTO,
    ProjectDTO,
    ReceiptDTO,
    ReimbursementDTO,
)
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

"""
Canonical Mental Model:
services_journal → Writes rows into GL tables and projections.

TL;DR:
if it writes Journal, JournalLine, BalanceMonthly, or StatMetric,
it belongs in services_journal.py.

Functions and helpers this file should contain:
ALLOWED_TYPES
ALLOWED_PERIOD_STATUS

Internal Helper Functions
(essential internal helpers imported elsewhere in finance.services_XXX)
_period_key_from(...) chk
_ensure_open_period(...) chk
ensure_account(...) chk
ensure_fund(...) chk
ensure_project(...) chk

Core journal operations:
post_journal(...) – the one true way to write GL entries. chk
reverse_journal(...) – “undo” a journal by posting an opposite entry. chk

All of these are “convenience wrappers” that call post_journal:
log_expense(payload, dry_run=False) -> ExpenseDTO chk
log_donation(payload, dry_run=False) -> DonationDTO chk
record_receipt(payload, dry_run=False) -> ReceiptDTO (TODO)
record_inkind(...) -> str chk
release_restriction(...) -> str chk

These are part of the write-path projection:
_apply_to_balances(lines, period_key) chk
rebuild_balances(period_from, period_to) chk
– it rewrites BalanceMonthly using journal lines.

Stats
record_stat_metric(...) -> str – it’s “off-GL” chk
but conceptually still a write, so it’s fine staying here for now.

"""

# -----------------
# Helpers & Ref's
# exported to other
# finance services
# -----------------


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


def _external_restriction_type(internal: str) -> str:
    """Map internal Fund.restriction -> external DTO string."""
    mapping = {
        "unrestricted": "unrestricted",
        "temp": "temporarily_restricted",
        "perm": "permanently_restricted",
    }
    return mapping.get(internal, "unrestricted")


# -----------------
# journal Entries
# Keep this here
# -----------------


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


# -----------------
# Reverse Journal Entry
# Keep this here
# -----------------


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


# -----------------
# Log Expense
# Keep this here
# -----------------


def log_expense(payload: dict, *, dry_run: bool = False) -> ExpenseDTO:
    """Slice implementation for finance_v2.log_expense(...).

    IMPORTANT:
      This function assumes any Governance / budget / policy checks have
      already been performed (for example via
      ``governance_v2.preview_spend_decision`` or a Finance helper).
      It MUST NOT perform policy decisions itself; its sole responsibility
      is to persist the approved expense as Finance facts (Journal rows).

    MVP behaviour:
      * require fund_id, project_id, occurred_on, vendor, amount_cents, category
      * post a balanced Journal entry (expense vs cash/bank)
      * return an ExpenseDTO summarising the entry

    Expected payload keys (matching finance_v2 contract docstring):

      Required:
        - fund_id:      ULID of fin_fund
        - project_id:   ULID of calendar project (or similar “bucket”)
        - occurred_on:  ISO-8601 date or datetime string
        - vendor:       free-text payee (or 'N/A')
        - amount_cents: integer cents (> 0)
        - category:     free-text category label

      Optional (honoured if present):
        - bank_account_code:    COA code for the cash/bank account (default '1000')
        - expense_account_code: COA code for the expense account (default '5200')
        - memo:                 free-text memo to attach to the Journal
        - external_ref_id:      ULID of related object (e.g. Allocation)
        - created_by_actor:     actor ULID
        - source:               free-text source label (default 'calendar')

    Raises:
        ValueError: if required fields are missing or malformed
                    (e.g. non-integer amount, amount <= 0).
        LookupError: if the referenced fund_id cannot be found.

    Returns:
        ExpenseDTO: PII-free summary of the (real or simulated) expense.
    """
    # ---- Required fields ----
    try:
        fund_id = payload["fund_id"]
        project_id = payload["project_id"]
        occurred_on = payload["occurred_on"]
        vendor = (payload.get("vendor") or "").strip()
        category = (payload.get("category") or "").strip()
        amount_raw = payload["amount_cents"]
    except KeyError as exc:
        # Let the contract layer classify this as bad_argument via _as_contract_error
        raise ValueError(f"missing required field: {exc.args[0]}") from exc

    try:
        amount_cents = int(amount_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("amount_cents must be an integer") from exc

    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    fund = db.session.get(Fund, fund_id)
    if not fund:
        # Let the contract layer classify this as not_found via _as_contract_error
        raise LookupError(f"unknown fund_id {fund_id!r}")

    # Normalise timestamp. post_journal expects an ISO-8601 string and will
    # derive any period information from it, so we pass this through unchanged.
    happened_at_utc = occurred_on

    # ---- Optional fields / defaults ----
    bank_account_code = payload.get("bank_account_code", "1000")  # Cash/bank
    expense_account_code = payload.get(
        "expense_account_code", "5200"
    )  # Supplies/expense
    memo = payload.get("memo") or (
        f"{category} — {vendor}" if vendor else category
    )
    external_ref_ulid = payload.get("external_ref_id")
    created_by_actor = payload.get("created_by_actor")
    source = payload.get("source", "calendar")

    # Dry-run: no DB writes, just a DTO that says what would happen
    if dry_run:
        return ExpenseDTO(
            id="DRY-RUN",
            fund_id=fund.ulid,
            project_id=project_id,
            occurred_on=happened_at_utc,
            vendor=vendor,
            amount_cents=amount_cents,
            category=category,
            approved_by_ulid=None,
            flags=["dry_run"],
        )

    # Build balanced journal lines: DR expense, CR cash/bank.
    # NOTE: post_journal already enforces period & balance rules and updates
    # BalanceMonthly, so we keep this thin.
    lines = [
        {
            "account_code": expense_account_code,
            "fund_code": fund.code,
            "project_ulid": project_id,
            "amount_cents": amount_cents,
            "memo": memo,
        },
        {
            "account_code": bank_account_code,
            "fund_code": fund.code,
            "project_ulid": project_id,
            "amount_cents": -amount_cents,
            "memo": memo,
        },
    ]

    journal_ulid = post_journal(
        happened_at_utc=happened_at_utc,
        source=source,
        description=memo or f"{category} expense",
        fund_code=fund.code,
        project_ulid=project_id,
        external_ref_ulid=external_ref_ulid,
        created_by_actor=created_by_actor,
        lines=lines,
    )

    return ExpenseDTO(
        id=journal_ulid,
        fund_id=fund.ulid,
        project_id=project_id,
        occurred_on=happened_at_utc,
        vendor=vendor,
        amount_cents=amount_cents,
        category=category,
        approved_by_ulid=None,
        flags=[],
    )


# -----------------
# Log Donation
# Keep this here
# -----------------


def log_donation(payload: dict, *, dry_run: bool = False) -> DonationDTO:
    """Slice implementation for finance_v2.log_donation(...).

    MVP behaviour:
      * require sponsor_ulid, fund_id, happened_at_utc, amount_cents
      * post a balanced Journal entry (cash/bank vs revenue)
      * return a DonationDTO summarising the entry
      * governance checks (fund archetypes, flags, restrictions) can be layered later

    Expected payload keys (matching finance_v2 contract docstring):

      Required:
        - sponsor_ulid:   ULID of the sponsor (from Sponsors slice)
        - fund_id:        ULID of fin_fund
        - happened_at_utc: ISO-8601 UTC timestamp string
        - amount_cents:   integer cents (> 0)

      Optional (honoured if present):
        - bank_account_code:     COA code for the cash/bank account (default '1000')
        - revenue_account_code:  COA code for the revenue account (default '4100')
        - memo:                  free-text memo to attach to the Journal
        - external_ref_ulid:     ULID of related object (e.g. pledge, receipt image)
        - created_by_actor:      actor ULID
        - source:                free-text source label (default 'sponsor')
        - flags:                 list[str] of tags (e.g. ['pledge_realization'])

    Raises:
        ValueError: if required fields are missing or malformed
                    (e.g. non-integer amount, amount <= 0).
        LookupError: if the referenced fund_id cannot be found.

    Returns:
        DonationDTO: PII-free summary of the (real or simulated) donation.
    """
    # ---- Required fields ----
    try:
        sponsor_ulid = payload["sponsor_ulid"]
        fund_id = payload["fund_id"]
        happened_at_utc = payload["happened_at_utc"]
        amount_raw = payload["amount_cents"]
    except KeyError as exc:
        raise ValueError(f"missing required field: {exc.args[0]}") from exc

    try:
        amount_cents = int(amount_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("amount_cents must be an integer") from exc

    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    fund = db.session.get(Fund, fund_id)
    if not fund:
        # _as_contract_error will map this to code="not_found"
        raise LookupError(f"unknown fund_id {fund_id!r}")

    # ---- Optional fields / defaults ----
    bank_account_code = payload.get("bank_account_code", "1000")  # Cash/bank
    revenue_account_code = payload.get(
        "revenue_account_code", "4100"
    )  # Contributions
    memo = payload.get("memo") or "Donation"
    external_ref_ulid = payload.get("external_ref_ulid")
    created_by_actor = payload.get("created_by_actor")
    source = payload.get("source", "sponsor")
    flags_list = list(payload.get("flags") or [])

    # Dry-run: no DB writes, just a DTO that says what would happen
    if dry_run:
        return DonationDTO(
            id="DRY-RUN",
            sponsor_ulid=sponsor_ulid,
            fund_id=fund.ulid,
            happened_at_utc=happened_at_utc,
            amount_cents=amount_cents,
            flags=flags_list + ["dry_run"],
        )

    # Build balanced journal lines: DR cash/bank, CR contribution revenue.
    lines = [
        {
            "account_code": bank_account_code,
            "fund_code": fund.code,
            "amount_cents": amount_cents,
            "memo": memo,
        },
        {
            "account_code": revenue_account_code,
            "fund_code": fund.code,
            "amount_cents": -amount_cents,
            "memo": memo,
        },
    ]

    journal_ulid = post_journal(
        source=source,
        external_ref_ulid=external_ref_ulid,
        happened_at_utc=happened_at_utc,
        currency="USD",
        memo=memo,
        lines=lines,
        created_by_actor=created_by_actor,
    )

    return DonationDTO(
        id=journal_ulid,
        sponsor_ulid=sponsor_ulid,
        fund_id=fund.ulid,
        happened_at_utc=happened_at_utc,
        amount_cents=amount_cents,
        flags=flags_list,
    )


# -----------------
# Record inkind Donation
# Keep this here
# -----------------


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


# -----------------
# Record Receipt
# NEW FUNCTION
# Keep this here
# -----------------


def record_receipt():
    pass


# -----------------
# Release Restriction
# Keep this here
# -----------------


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


# -----------------
# Balances Projection
# Keep this here
# -----------------


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


# -----------------
# Rebuild Balances
# Keep this here
# -----------------


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


# -----------------
# statistical metrics
# (DRMO non-monetary)
# Keep this here
# -----------------


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
