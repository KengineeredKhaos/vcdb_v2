# app/extensions/contracts/funding_v2.py

from __future__ import annotations

from dataclasses import dataclass

from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms

from ._funding_dto import MoneyByKeyDTO, MoneyLinksDTO
from .calendar_v2 import FundingDemandDTO, get_funding_demand
from .finance_v2 import (
    FundingDemandMoneyViewDTO,
    get_funding_demand_money_view,
)
from .sponsors_v2 import FundingIntentTotalsDTO, get_funding_intent_totals

# -----------------
# ContractError Handling
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc
    msg = str(exc) or exc.__class__.__name__
    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=msg,
            http_status=400,
        )
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found",
            where=where,
            message=msg,
            http_status=404,
        )
    if isinstance(exc, PermissionError):
        return ContractError(
            code="permission_denied",
            where=where,
            message=msg,
            http_status=403,
        )
    return ContractError(
        code="internal",
        where=where,
        message=msg,
        http_status=500,
    )


# -----------------
# DTO'S
# (new paradigm)
# -----------------


@dataclass(frozen=True)
class FundingDemandMoneyTotalsDTO:
    pledged_cents: int
    received_cents: int
    reserved_cents: int
    encumbered_cents: int
    spent_cents: int

    available_cents: int
    unmet_goal_cents: int


@dataclass(frozen=True)
class FundingDemandDashboardDTO:
    as_of_iso: str
    meta: FundingDemandDTO
    totals: FundingDemandMoneyTotalsDTO

    pledged_by_sponsor: tuple[MoneyByKeyDTO, ...]
    received_by_fund: tuple[MoneyByKeyDTO, ...]
    reserved_by_fund: tuple[MoneyByKeyDTO, ...]
    encumbered_by_fund: tuple[MoneyByKeyDTO, ...]
    spent_by_expense_kind: tuple[MoneyByKeyDTO, ...]
    income_by_income_kind: tuple[MoneyByKeyDTO, ...]

    links: MoneyLinksDTO


# -----------------
# New Paradigm
# -----------------


"""
Composite Contract Signature
# app/extensions/contracts/funding_v2.py

def get_funding_demand_dashboard(
    funding_demand_ulid: str,
    *,
    as_of_iso: str | None = None,
) -> FundingDemandDashboardDTO:
    ...

Behavior:

Get demand meta from Calendar.
Get pledge totals from Sponsors.
Get money totals from Finance.
Compute convenience fields and return the full DTO.

These contracts expect these providers to exist:

Calendar:
app.slices.calendar.services_funding.get_funding_demand(...)

Sponsors:
app.slices.sponsors.services_funding.get_funding_intent_totals(...)

Finance:
app.slices.finance.services_dashboard.get_funding_demand_money_view(...)

If any provider isn’t there yet, you’ll get a
ContractError(code="provider_missing", ...)
pointing exactly at the missing callable.
"""


def _merge_links(
    intent_links: MoneyLinksDTO,
    money_links: MoneyLinksDTO,
) -> MoneyLinksDTO:
    return MoneyLinksDTO(
        income_journal_ulids=money_links.income_journal_ulids,
        expense_journal_ulids=money_links.expense_journal_ulids,
        reserve_ulids=money_links.reserve_ulids,
        encumbrance_ulids=money_links.encumbrance_ulids,
        pledge_ulids=intent_links.pledge_ulids,
        donation_ulids=intent_links.donation_ulids,
    )


def get_funding_demand_dashboard(
    funding_demand_ulid: str,
    *,
    as_of_iso: str | None = None,
) -> FundingDemandDashboardDTO:
    where = "funding_v2.get_funding_demand_dashboard"
    try:
        as_of = as_of_iso or now_iso8601_ms()

        meta: FundingDemandDTO = get_funding_demand(funding_demand_ulid)

        intent: FundingIntentTotalsDTO = get_funding_intent_totals(
            funding_demand_ulid
        )

        money: FundingDemandMoneyViewDTO = get_funding_demand_money_view(
            funding_demand_ulid,
            as_of_iso=as_of,
        )

        # Convenience computed fields
        available = (
            money.received_cents
            - money.reserved_cents
            - money.encumbered_cents
            - money.spent_cents
        )
        unmet_goal = meta.goal_cents - money.received_cents
        if unmet_goal < 0:
            unmet_goal = 0

        totals = FundingDemandMoneyTotalsDTO(
            pledged_cents=intent.pledged_cents,
            received_cents=money.received_cents,
            reserved_cents=money.reserved_cents,
            encumbered_cents=money.encumbered_cents,
            spent_cents=money.spent_cents,
            available_cents=available,
            unmet_goal_cents=unmet_goal,
        )

        links = _merge_links(intent.links, money.links)

        return FundingDemandDashboardDTO(
            as_of_iso=as_of,
            meta=meta,
            totals=totals,
            pledged_by_sponsor=intent.pledged_by_sponsor,
            received_by_fund=money.received_by_fund,
            reserved_by_fund=money.reserved_by_fund,
            encumbered_by_fund=money.encumbered_by_fund,
            spent_by_expense_kind=money.spent_by_expense_kind,
            income_by_income_kind=money.income_by_income_kind,
            links=links,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc
