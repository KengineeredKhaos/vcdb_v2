# app/slices/finance/services_funds.py
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
from app.slices.finance import services_journal
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

"""
Canonical Mental Model:
services_funds → Defines and administrates buckets (funds, budgets, periods).

TL;DR:
if it’s about what funds exist, their status, or budgets,
it belongs in services_funds.py.

Functions and helpers this file should contain:

Period admin:
set_period_status(period_key, status) – open / soft_closed / closed.

Fund lifecycle:
create_fund(payload) -> FundDTO
    Probably uses ensure_fund under the hood.
    Likely needs to understand Governance fund_archetypes semantics eventually.

get_fund_summary(fund_ulid) -> FundDTO
    Summaries of allocations / net movements for that Fund,
    by querying BalanceMonthly and/or JournalLines.

Transfers & budgets:
transfer(payload) -> dict
    Conceptually: “move money between fund/project buckets”,
    but it will internally call services_journal.post_journal(...)
    to actually write the entry.

set_budget(payload) -> BudgetDTO
    Connect policy_budget (Governance) with a concrete “budget row”
    in Finance, if you store it here.

"""


# -----------------
# Internal helpers
# besides imports
# -----------------


def get_fund_archetypes():
    """
    Fetch current list of fund archetype from governance policy
    "fund_archetypes": [
          { "key": "general_unrestricted", "restriction": "unrestricted", "label": "General Unrestricted" },
          { "key": "grant_advance",        "restriction": "temporarily_restricted", "label": "Grant (advance funds)" },
          { "key": "grant_reimbursement",  "restriction": "temporarily_restricted", "label": "Grant (reimbursement)" },
          { "key": "vet_only",             "restriction": "temporarily_restricted", "label": "Veteran-only" },
          { "key": "local_only",           "restriction": "temporarily_restricted", "label": "Local-only" },
          { "key": "local_vet_only",       "restriction": "temporarily_restricted", "label": "Local veteran-only" },
          { "key": "match_funds",          "restriction": "temporarily_restricted", "label": "Match funds" },
          { "key": "inkind_tracking",      "restriction": "unrestricted", "label": "In-kind tracking only" }
    ]
    """
    pass


def get_projects():
    """
    Fetch current list of Calendar Projects
    """
    pass


# -----------------
# Set Period Status
# Move to services_funds
# -----------------


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


# -----------------
# Create Fund
# services_funds
# -----------------


def create_fund(payload: dict) -> FundDTO:
    """
    Slice implementation for finance_v2.create_fund(...).

    This helper creates or updates a Fund "bucket" that represents a pot
    of money with a particular restriction type (unrestricted, temporary,
    permanent). It is intentionally idempotent:

      * If a Fund with the given ``code`` already exists, its ``name``,
        restriction, and active status are updated and the existing row
        is returned.
      * If no such Fund exists, a new row is created and returned.

    Expected payload keys (from finance_v2 contract):

      Required:
        - code: str
            Short code for the fund (e.g. "UNRESTRICTED",
            "STANDDOWN_2026").
        - name: str
            Human-friendly name for the fund.
        - restriction_type: str
            One of:
              * "unrestricted"
              * "temporarily_restricted"
              * "permanently_restricted"

      Optional:
        - active: bool (default: True)

    Raises:
        ValueError:
            * if code or name are missing/empty
            * if restriction_type is not one of the allowed values

        LookupError:
            * if the Fund row cannot be loaded after creation
              (should not normally happen; indicates a DB issue).

    Returns:
        FundDTO:
            A PII-free description of the Fund, with ``balance_cents``
            initialised to 0. (Balance computation is handled by report
            helpers, not this function.)
    """
    # ---- Extract and validate fields from payload ----
    code = (payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    restriction_type = (payload.get("restriction_type") or "").strip()
    active = bool(payload.get("active", True))

    if not code:
        raise ValueError("code is required")
    if not name:
        raise ValueError("name is required")

    # Map external restriction_type -> internal Fund.restriction
    # Fund.restriction uses a short code: 'unrestricted' | 'temp' | 'perm'
    mapping = {
        "unrestricted": "unrestricted",
        "temporarily_restricted": "temp",
        "permanently_restricted": "perm",
    }
    if restriction_type not in mapping:
        raise ValueError(
            "restriction_type must be one of: "
            "'unrestricted', 'temporarily_restricted', "
            "'permanently_restricted'"
        )
    restriction_internal = mapping[restriction_type]

    # ---- Ensure Fund row exists (idempotent upsert) ----
    # This reuses the lower-level helper that enforces the internal
    # restriction codes and handles re-activation.
    fund_ulid = services_journal.ensure_fund(
        code=code,
        name=name,
        restriction=restriction_internal,
    )

    fund = db.session.get(Fund, fund_ulid)
    if not fund:
        # Extremely unlikely if ensure_fund succeeded; treat as a hard error.
        raise LookupError(
            f"failed to load Fund after ensure_fund for code {code!r}"
        )

    # Honour explicit 'active' flag if caller provided False.
    if fund.active != active:
        fund.active = active
        db.session.commit()

    # ---- Build DTO ----
    dto = FundDTO()
    dto.id = fund.ulid
    dto.name = fund.name
    dto.restriction_type = restriction_type
    dto.starts_on = None
    dto.expires_on = None
    dto.balance_cents = 0  # actual balance is computed by reporting helpers

    # Emit a generic event so Ledger / observers can track configuration changes.
    event_bus.emit(
        domain="finance",
        operation="fund.upserted",
        entity="fund",
        entity_ulid=fund.ulid,
        meta={
            "code": fund.code,
            "restriction_type": restriction_type,
            "active": fund.active,
        },
    )

    return dto


# -----------------
# Transfer
# services_funds
# -----------------


def transfer():
    """
    Transfer dedicated funds from one account|fund|project to another
    """
    pass


# -----------------
# Set Budget
# services_funds
# -----------------


def set_budget():
    """
    Calendar Set Project Budget

    policy_projects

      "project_types": [
      { "key": "operations",          "label": "Office operations & supplies" },
      { "key": "overhead",            "label": "Overhead (lease, utilities, insurance, phone, hosting)" },
      { "key": "travel",              "label": "Travel & per diem" },
      { "key": "freight",             "label": "Shipping & freight" },
      { "key": "solicitation",        "label": "Fundraising mailers (printing, envelopes, postage)" },
      { "key": "recruitment",         "label": "Volunteer recruitment" },
      { "key": "fund_raising",        "label": "General fundraising event" },
      { "key": "sponsor_recognition", "label": "Sponsor recognition swag" },
      { "key": "lateral",             "label": "Donations to other nonprofits" },
      { "key": "outreach",            "label": "County-wide homeless outreach" },
      { "key": "stand_down",          "label": "Annual Stand Down event" },
      { "key": "memorial_ride",       "label": "Rick Rice Memorial Ride" },
      { "key": "veterans_ride",       "label": "Frank Parker Veterans Ride" }
    ]

    policy_budget

     "lines": [
        {
          "fund_archetype_key": "grant_advance",
          "fund_code": "ELKS-FREEDOM-2025",
          "project_type_key": "stand_down",
          "project_code": "Stand-Down-2025",
          "amount_cents": 200000,
          "source": "grant:ELKS_FREEDOM",
          "status": "adopted"
        }
    ]
    """
    pass


# -----------------
# Get Fund Summary
# services_funds
# -----------------


def get_fund_summary(fund_ulid: str) -> FundDTO:
    """
    Slice implementation for finance_v2.get_fund_summary(...).

    Given a Fund ULID, returns a PII-free summary of that fund plus its
    current asset balance.

    Semantics (MVP):

    - Look up the Fund by ULID.
    - Compute the aggregate balance as the sum of BalanceMonthly.net_cents
      for this fund across all *asset* accounts.
    - Map the internal Fund.restriction ('unrestricted'|'temp'|'perm')
      into the external restriction_type used by FundDTO
      ('unrestricted'|'temporarily_restricted'|'permanently_restricted').

    This is a read-only helper; it performs no writes and emits no events.

    Raises:
        LookupError:
            if the Fund cannot be found for the given ULID.
    """
    fund = db.session.get(Fund, fund_ulid)
    if fund is None:
        raise LookupError(f"fund {fund_ulid!r} not found")

    # Map internal restriction code -> external DTO string.
    restriction_map = {
        "unrestricted": "unrestricted",
        "temp": "temporarily_restricted",
        "perm": "permanently_restricted",
    }
    restriction_type = restriction_map.get(fund.restriction, "unrestricted")

    # Aggregate current balance from BalanceMonthly.
    #
    # We treat "fund balance" as the sum of net_cents across all *asset*
    # accounts for this fund. For a small nonprofit with a single bank
    # account, this effectively answers “how much cash is earmarked for
    # this fund?”.
    balance_q = (
        select(func.coalesce(func.sum(BalanceMonthly.net_cents), 0))
        .join(
            Account,
            Account.code == BalanceMonthly.account_code,
        )
        .where(
            BalanceMonthly.fund_code == fund.code,
            Account.type == "asset",
        )
    )
    balance_cents = int(db.session.execute(balance_q).scalar_one() or 0)

    return FundDTO(
        id=fund.ulid,
        name=fund.name,
        restriction_type=restriction_type,
        starts_on=None,  # can be wired later if/when Fund gains these fields
        expires_on=None,
        balance_cents=balance_cents,
    )


# -----------------
# Read-side: list funds with balances
# -----------------


def list_funds_with_balances(
    *, include_inactive: bool = False
) -> List[FundDTO]:
    """
    Slice implementation for finance_v2.list_funds(...).

    Returns a list of FundDTOs, each including the current asset balance
    for that fund. This is read-only and does not emit events.

    Semantics (MVP):

      * Load all Fund rows (optionally excluding inactive funds).
      * Aggregate BalanceMonthly.net_cents for each fund across all
        asset accounts.
      * Map internal Fund.restriction codes to the external
        'restriction_type' strings expected by FundDTO.

    Args:
        include_inactive:
            When False (default), only active funds are returned.
            When True, all funds are returned.

    Raises:
        None specific; callers should handle general DB errors if needed.

    Returns:
        List[FundDTO]:
            One DTO per fund, suitable for driving an Admin “Funds”
            status screen or Governance/Calendar allocation views.
    """
    # ---- Load funds ----
    q = select(Fund)
    if not include_inactive:
        q = q.where(Fund.active.is_(True))

    funds = db.session.execute(q.order_by(Fund.code)).scalars().all()

    if not funds:
        return []

    fund_codes = {f.code for f in funds}

    # ---- Aggregate balances by fund_code across asset accounts ----
    bal_q = (
        select(
            BalanceMonthly.fund_code,
            func.coalesce(func.sum(BalanceMonthly.net_cents), 0).label(
                "balance_cents"
            ),
        )
        .join(
            Account,
            Account.code == BalanceMonthly.account_code,
        )
        .where(
            BalanceMonthly.fund_code.in_(fund_codes),
            Account.type == "asset",
        )
        .group_by(BalanceMonthly.fund_code)
    )

    rows = db.session.execute(bal_q).all()
    balances_by_code = {row[0]: int(row[1] or 0) for row in rows}

    # ---- Build DTOs ----
    result: List[FundDTO] = []

    for fund in funds:
        dto = FundDTO()
        dto.id = fund.ulid
        dto.name = fund.name
        dto.restriction_type = _external_restriction_type(fund.restriction)
        dto.starts_on = None  # can be wired later if Fund grows date fields
        dto.expires_on = None
        dto.balance_cents = balances_by_code.get(fund.code, 0)
        result.append(dto)

    return result
