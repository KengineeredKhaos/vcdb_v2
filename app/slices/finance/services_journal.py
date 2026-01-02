# app/slices/finance/services_journal.py
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts.finance_v2 import (
    DonationDTO,
    ExpenseDTO,
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

# -----------------
# Constants
# Declarations
# -----------------

ALLOWED_TYPES = {"asset", "liability", "net_assets", "revenue", "expense"}
ALLOWED_PERIOD_STATUS = {"open", "soft_closed", "closed"}

# -----------------
# Chart of Accounts
# & rulebook (MVP)
# (details below)
# -----------------

COA: dict[str, dict[str, str]] = {
    # --------
    # ASSETS
    # --------
    "cash": {
        "code": "1000",
        "name": "Cash - Operating Bank",
        "type": "asset",
    },
    "petty_cash": {
        "code": "1010",
        "name": "Petty Cash",
        "type": "asset",
    },
    "recv_grants_contrib": {
        "code": "1100",
        "name": "Grants & Contributions Receivable",
        "type": "asset",
    },
    "undeposited_funds": {
        "code": "1200",
        "name": "Undeposited Funds",
        "type": "asset",
    },  # optional but handy
    "prepaid_expenses": {
        "code": "1300",
        "name": "Prepaid Expenses",
        "type": "asset",
    },
    "fixed_assets": {
        "code": "1500",
        "name": "Fixed Assets",
        "type": "asset",
    },
    "accum_depr": {
        "code": "1590",
        "name": "Accumulated Depreciation",
        "type": "asset",
    },  # contra-asset
    # -------------
    # LIABILITIES
    # -------------
    "accounts_payable": {
        "code": "2000",
        "name": "Accounts Payable",
        "type": "liability",
    },
    "accrued_liab": {
        "code": "2100",
        "name": "Accrued Liabilities",
        "type": "liability",
    },
    "refundable_adv": {
        "code": "2200",
        "name": "Refundable Advances / Deferred Revenue",
        "type": "liability",
    },
    # -----------
    # NET ASSETS
    # -----------
    "na_without_dr": {
        "code": "3000",
        "name": "Net Assets Without Donor Restrictions",
        "type": "net_assets",
    },
    "na_with_dr": {
        "code": "3100",
        "name": "Net Assets With Donor Restrictions",
        "type": "net_assets",
    },
    # --------
    # REVENUE
    # --------
    "contrib_revenue": {
        "code": "4000",
        "name": "Contributions",
        "type": "revenue",
    },
    "grant_revenue": {
        "code": "4100",
        "name": "Grant Revenue",
        "type": "revenue",
    },
    "program_rev": {
        "code": "4200",
        "name": "Program Service Revenue",
        "type": "revenue",
    },
    "event_rev": {
        "code": "4300",
        "name": "Fundraising Event Revenue",
        "type": "revenue",
    },
    "merch_rev": {
        "code": "4400",
        "name": "Merchandise Sales",
        "type": "revenue",
    },
    "inkind_revenue": {
        "code": "4500",
        "name": "In-Kind Contributions",
        "type": "revenue",
    },
    "other_income": {
        "code": "4900",
        "name": "Other Income",
        "type": "revenue",
    },
    # ---------
    # EXPENSES (NATURAL)
    # ---------
    "direct_program_costs": {
        "code": "5000",
        "name": "Direct Program Costs",
        "type": "expense",
    },
    "supplies": {
        "code": "5100",
        "name": "Supplies",
        "type": "expense",
    },
    "occupancy": {
        "code": "5200",
        "name": "Occupancy (Rent & Utilities)",
        "type": "expense",
    },
    "insurance": {
        "code": "5300",
        "name": "Insurance",
        "type": "expense",
    },
    "professional_fees": {
        "code": "5400",
        "name": "Professional Fees",
        "type": "expense",
    },
    "software_it": {
        "code": "5500",
        "name": "Software & IT",
        "type": "expense",
    },
    "postage_shipping": {
        "code": "5600",
        "name": "Postage, Freight & Shipping",
        "type": "expense",
    },
    "travel_meetings": {
        "code": "5700",
        "name": "Travel & Meetings",
        "type": "expense",
    },
    "market_cultivation": {
        "code": "5800",
        "name": "Marketing / Donor & Sponsor Cultivation",
        "type": "expense",
    },
    "event_expense": {
        "code": "5900",
        "name": "Event Expenses",
        "type": "expense",
    },
    "bank_merchant_fees": {
        "code": "5950",
        "name": "Bank & Merchant Processing Fees",
        "type": "expense",
    },
    "cogs": {"code": "6000", "name": "Cost of Goods Sold", "type": "expense"},
    "depreciation": {
        "code": "6100",
        "name": "Depreciation Expense",
        "type": "expense",
    },
    "other_expense": {
        "code": "6900",
        "name": "Other Expense",
        "type": "expense",
    },
}


"""
Always Balanced Pairs:
assets-liability | revenue-expense

- **1000–1999**: Assets (what we own)
- **2000–2999**: Liabilities (what we owe)
- **3000–3999**: Net Assets (what’s left over, unrestricted vs restricted)
- **4000–4999**: Revenue (money / value coming in)
- **5000–5999**: Expenses – Natural cost of doing busienss
- **6000–6999**: Expenses – cost of goods, depreciation, misc
"""


def ensure_default_accounts() -> None:
    """Ensure the core chart-of-accounts rows exist.

    This is intended for CLI / test setup. It is *not* called on each request.
    """
    for spec in COA.values():
        ensure_account(
            code=spec["code"],
            name=spec["name"],
            type=spec["type"],
        )


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


def ensure_fund(*, code: str, name: str, restriction: str) -> Fund:
    """
    Upsert a Fund by its *code* (human-stable key).

    Internally we store restriction as:
      - unrestricted
      - temp
      - perm

    Accept common external spellings and normalize them.
    """
    restriction_raw = (restriction or "").strip()

    mapping = {
        "unrestricted": "unrestricted",
        "temp": "temp",
        "temporary": "temp",
        "temporarily_restricted": "temp",
        "perm": "perm",
        "permanent": "perm",
        "permanently_restricted": "perm",
    }
    restriction_norm = mapping.get(restriction_raw, restriction_raw)

    if restriction_norm not in {"unrestricted", "temp", "perm"}:
        raise ValueError(f"invalid restriction type: {restriction_raw}")

    row = db.session.execute(
        select(Fund).where(Fund.code == code)
    ).scalar_one_or_none()
    if not row:
        row = Fund(
            code=code, name=name, restriction=restriction_norm, active=True
        )
        db.session.add(row)
        db.session.flush()
    else:
        row.name = name
        row.restriction = restriction_norm
        db.session.flush()
    return row


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
    """
    Write a balanced journal entry (header + lines) and update BalanceMonthly.

    Conventions:
      - Each line uses signed cents:
          +amount_cents => debit
          -amount_cents => credit
      - Journal must balance: sum(amount_cents) == 0
      - fund_code + account_code are *codes* (human-stable), not ULIDs.
    """
    if not source:
        raise ValueError("source is required")
    currency = (currency or "USD").upper()
    if currency != "USD":
        raise ValueError("only USD supported for now")

    if not isinstance(lines, list) or not lines:
        raise ValueError("lines must be a non-empty list")

    period_key = _period_key_from(happened_at_utc)
    _ensure_open_period(period_key)

    # Validate line shape + balance
    total = 0
    acct_codes: set[str] = set()
    fund_codes: set[str] = set()

    for i, l in enumerate(lines, start=1):
        if not isinstance(l, dict):
            raise ValueError(f"line {i} must be a dict")
        acct = l.get("account_code")
        fund = l.get("fund_code")
        amt = l.get("amount_cents")

        if not acct or not isinstance(acct, str):
            raise ValueError(f"line {i}: account_code is required")
        if not fund or not isinstance(fund, str):
            raise ValueError(f"line {i}: fund_code is required")
        if amt is None:
            raise ValueError(f"line {i}: amount_cents is required")

        try:
            amt_i = int(amt)
        except Exception as exc:
            raise ValueError(f"line {i}: amount_cents must be int") from exc

        if amt_i == 0:
            raise ValueError(f"line {i}: amount_cents cannot be 0")

        total += amt_i
        acct_codes.add(acct)
        fund_codes.add(fund)

    if total != 0:
        raise ValueError("journal not balanced (sum(amount_cents) != 0)")

    # Verify referenced codes exist (fail fast with a helpful message)
    existing_accts = set(
        db.session.execute(
            select(Account.code).where(Account.code.in_(acct_codes))
        )
        .scalars()
        .all()
    )
    missing_accts = acct_codes - existing_accts
    if missing_accts:
        raise LookupError(f"unknown account_code(s): {sorted(missing_accts)}")

    existing_funds = set(
        db.session.execute(select(Fund.code).where(Fund.code.in_(fund_codes)))
        .scalars()
        .all()
    )
    missing_funds = fund_codes - existing_funds
    if missing_funds:
        raise LookupError(f"unknown fund_code(s): {sorted(missing_funds)}")

    # Persist journal
    j = Journal(
        source=source,
        external_ref_ulid=external_ref_ulid,
        currency=currency,
        period_key=period_key,
        happened_at_utc=happened_at_utc,
        memo=(memo or None),
        created_by_actor=created_by_actor,
        posted_at_utc=now_iso8601_ms(),
    )
    db.session.add(j)
    db.session.flush()  # assign j.ulid

    for seq, l in enumerate(lines, start=1):
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

    _apply_to_balances(lines=lines, period_key=period_key)
    db.session.commit()

    # Emit cross-slice audit (NOT the Finance journal)
    event_bus.emit(
        domain="finance",
        operation="journal_posted",
        request_id=j.ulid,
        actor_ulid=created_by_actor,
        target_ulid=j.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "period_key": period_key,
            "source": source,
            "external_ref_ulid": external_ref_ulid,
            "line_count": len(lines),
            "fund_codes": sorted(fund_codes),
        },
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
# Expense Rule Helper
# -----------------


def _select_expense_accounts(*, expense_type: str) -> tuple[str, str]:
    key = (expense_type or "").strip()
    if not key:
        key = "direct_program_costs"

    try:
        expense_acct = COA[key]["code"]
    except KeyError as exc:
        raise KeyError(
            f"Unknown expense COA key {key!r}. Select a valid expense_type."
        ) from exc

    cash_acct = COA["cash"]["code"]
    return expense_acct, cash_acct


# -----------------
# Log Expense
# -----------------


# ---- Required fields ----
def log_expense(payload: dict, *, dry_run: bool = False) -> ExpenseDTO:
    """Slice implementation for finance_v2.log_expense(...).

    Notes:
      - This writes Finance facts only (Journal rows). It assumes any
        governance/budget checks already happened upstream.
      - `external_ref_ulid` is the canonical payload key.
        (We also accept legacy `external_ref_id` for safety.)

    IMPORTANT:
      This function assumes any Governance / budget / policy checks have
      already been performed (for example via
      ``governance_v2.preview_spend_decision`` or a Finance helper).
      It MUST NOT perform policy decisions itself; its sole responsibility
      is to persist the approved expense as Finance facts (Journal rows).

    MVP behaviour:
      * require fund_id, project_id, happened_at_utc, vendor, category, amount_cents
      * choose an expense account based on `category`
      * credit Operating Cash (1000) by default
      * post a balanced Journal entry and return an ExpenseDTO

    Callers MAY override:
      * `bank_account_code` (e.g. petty cash 1010)
      * `expense_account_code` (explicit COA code)

    Expected payload keys (matching finance_v2 contract docstring):

      Required:
        - fund_id:      ULID of fin_fund
        - project_id:   ULID of calendar project (or similar “bucket”)
        - happened_at_utc:  ISO-8601 date or datetime string
        - vendor:       free-text payee (or 'N/A')
        - amount_cents: integer cents (> 0)
        - expense_type: free-text category label

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
        happened_at_utc = payload["happened_at_utc"]
        vendor = payload["vendor"]
        expense_type = payload["expense_type"]
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
        raise LookupError(f"unknown fund_id {fund_id!r}")

    happened_at_utc = str(happened_at_utc)

    # ---- Optional fields / defaults ----
    bank_account_code = payload.get("bank_account_code")
    expense_account_code = payload.get("expense_account_code")

    if bank_account_code is None or expense_account_code is None:
        expense_acct, cash_acct = _select_expense_accounts(
            expense_type=expense_type
        )

        if expense_account_code is None:
            expense_account_code = expense_acct
        if bank_account_code is None:
            bank_account_code = cash_acct

    memo = payload.get("memo") or (
        f"{expense_type} — {vendor}" if vendor else str(expense_type)
    )

    # Canonical external ref key is external_ref_ulid; accept legacy too.
    external_ref_ulid = payload.get("external_ref_ulid") or payload.get(
        "external_ref_id"
    )

    created_by_actor = payload.get("created_by_actor")
    source = payload.get("source", "expense")

    if dry_run:
        dto: ExpenseDTO = {
            "id": "DRY-RUN",
            "fund_id": fund.ulid,
            "project_id": project_id,
            "happened_at_utc": happened_at_utc,
            "vendor": vendor,
            "amount_cents": amount_cents,
            "expense_type": expense_type,
            "approved_by_ulid": None,
            "flags": ["dry_run"],
        }
        return dto

    else:
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
            source=source,
            external_ref_ulid=external_ref_ulid,
            happened_at_utc=happened_at_utc,
            currency="USD",
            memo=memo,
            lines=lines,
            created_by_actor=created_by_actor,
        )

        dto: ExpenseDTO = {
            "id": journal_ulid,
            "fund_id": fund.ulid,
            "project_id": project_id,
            "happened_at_utc": happened_at_utc,
            "vendor": vendor,
            "amount_cents": amount_cents,
            "expense_type": expense_type,
            "approved_by_ulid": None,
            "flags": ["posted"],
        }
        return dto


# -----------------
# Donation Rule Helper
# -----------------


def _select_donation_accounts(
    *, fund: Fund, flags: list[str] | None
) -> tuple[str, str]:
    """Decide which accounts to use for a donation.

    - Defaults to DR cash, CR contributions revenue.
    - If flags include grant-related tags, use grant revenue instead.
    - If flags include "undeposited", debit Undeposited Funds instead of Cash.
    - In-kind donations should use record_inkind(), not log_donation().
    """
    flag_set = set(flags or [])

    if "inkind" in flag_set:
        raise ValueError("inkind donations must use record_inkind(...)")

    revenue_key = "contrib_revenue"
    if "reimbursable" in flag_set or "grant_elks_freedom" in flag_set:
        revenue_key = "grant_revenue"

    cash_key = "undeposited_funds" if "undeposited" in flag_set else "cash"

    cash_acct = COA[cash_key]["code"]
    revenue_acct = COA[revenue_key]["code"]
    return cash_acct, revenue_acct


# -----------------
# Log Donation
# -----------------


def log_donation(payload: dict, *, dry_run: bool = False) -> DonationDTO:
    """Slice implementation for finance_v2.log_donation(...).

    MVP behaviour:
      * require sponsor_ulid, fund_id, happened_at_utc, amount_cents
      * post a balanced Journal entry (cash/bank vs revenue)
      * return a DonationDTO summarising the entry

    Default account logic:
      * Debit Operating Cash (1000) unless caller overrides `bank_account_code`.
      * Credit Contributions – Cash Donations (4100) unless caller overrides
        `revenue_account_code`. If you later want to distinguish restricted vs
        unrestricted at the account level, you can swap the default here
        based on `fund.restriction` or flags.

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
    flags_list = list(payload.get("flags") or [])

    bank_account_code = payload.get("bank_account_code")
    revenue_account_code = payload.get("revenue_account_code")

    if bank_account_code is None or revenue_account_code is None:
        # Let the rulebook choose sensible defaults.
        cash_acct, rev_acct = _select_donation_accounts(
            fund=fund,
            flags=flags_list,
        )
        if bank_account_code is None:
            bank_account_code = cash_acct
        if revenue_account_code is None:
            revenue_account_code = rev_acct

    memo = payload.get("memo") or "Donation"
    external_ref_ulid = payload.get("external_ref_ulid")
    created_by_actor = payload.get("created_by_actor")
    source = payload.get("source", "sponsor")

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
# -----------------


def record_inkind(
    *,
    happened_at_utc: str,
    fund_code: str,
    amount_cents: int,
    expense_acct: str | None = None,
    revenue_acct: str | None = None,
    memo: Optional[str],
    external_ref_ulid: Optional[str],
    created_by_actor: Optional[str],
    valuation_basis: str,
) -> str:
    if amount_cents is None or int(amount_cents) <= 0:
        raise ValueError("amount_cents must be > 0")
    if not valuation_basis or not str(valuation_basis).strip():
        raise ValueError("valuation_basis required")

    if expense_acct is None:
        expense_acct = COA["supplies"]["code"]  # donated consumables
        # or COA["direct_program_costs"]["code"]  program items/consumables
        # or COA["event_expenses"]["code"]  event-specific donations
        # or COA["fixed_assets"]["code"]  hard goods/equip/durable assets
        # or COA["professional_fees"]["code"]  professional services
    if revenue_acct is None:
        revenue_acct = COA["inkind_revenue"]["code"]

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
# -----------------


def record_receipt():
    pass


# -----------------
# Release Restriction
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
                (
                    BalanceMonthly.project_ulid.is_(project)
                    if project is None
                    else BalanceMonthly.project_ulid == project
                ),
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
        operation="balance_rebuild",
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
        operation="stat_recorded",
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
