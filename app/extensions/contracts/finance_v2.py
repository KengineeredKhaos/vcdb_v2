# app/extensions/contracts/finance_v2.py

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from app.extensions.errors import ContractError

from ._funding_dto import MoneyByKeyDTO, MoneyLinksDTO

"""
Config / setup
finance_v2.create_grant(...) -> GrantDTO
services_grants.create_grant(payload) -> GrantDTO

Paperwork flows
finance_v2.submit_reimbursement(...) -> ReimbursementDTO
services_grants.submit_reimbursement(payload) -> ReimbursementDTO
finance_v2.mark_disbursed(...) -> ReimbursementDTO
services_grants.mark_disbursed(payload) -> ReimbursementDTO

Future reporting
finance_v2.prepare_grant_report(...) -> dict
services_grants.prepare_grant_report(payload) -> dict (stub, clearly documented)

No Journal writes in any of these; all actual money in/out still flows through
log_donation / log_expense in services_journal, exactly on the line you wanted.
"""

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
# DTO's
# (new paradigm)
# -----------------


@dataclass(frozen=True)
class FundingDemandMoneyViewDTO:
    funding_demand_ulid: str

    # Totals (presentation cents; positive)
    received_cents: int
    reserved_cents: int
    encumbered_cents: int
    spent_cents: int

    # Drilldowns
    received_by_fund: tuple[MoneyByKeyDTO, ...]
    reserved_by_fund: tuple[MoneyByKeyDTO, ...]
    encumbered_by_fund: tuple[MoneyByKeyDTO, ...]
    spent_by_expense_kind: tuple[MoneyByKeyDTO, ...]
    income_by_income_kind: tuple[MoneyByKeyDTO, ...]

    # ULID trace links
    links: MoneyLinksDTO


# -----------------
# New Paradigm
# -----------------


def _load_provider(where: str):
    """
    Finance slice must provide a read-only function with this signature:

        get_funding_demand_money_view(
            funding_demand_ulid: str,
            *,
            as_of_iso: str | None = None,
        ) -> dict[str, Any]

    Expected keys:
      funding_demand_ulid
      received_cents, reserved_cents, encumbered_cents, spent_cents
      received_by_fund, reserved_by_fund, encumbered_by_fund:
          list[{"key": fund_key, "amount_cents": int}, ...]
      spent_by_expense_kind:
          list[{"key": expense_kind, "amount_cents": int}, ...]
      income_by_income_kind:
          list[{"key": income_kind, "amount_cents": int}, ...]

      income_journal_ulids, expense_journal_ulids, reserve_ulids,
      encumbrance_ulids
    """
    try:
        mod = importlib.import_module("app.slices.finance.services_dashboard")
        fn = getattr(mod, "get_funding_demand_money_view")
        return fn
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            code="provider_missing",
            where=where,
            message=(
                "Finance provider missing: "
                "app.slices.finance.services_dashboard.get_funding_demand_money_view"
            ),
            http_status=500,
        ) from exc


def _to_money_by_key(rows: object) -> tuple[MoneyByKeyDTO, ...]:
    out: list[MoneyByKeyDTO] = []
    for r in rows or []:
        out.append(
            MoneyByKeyDTO(
                key=str(r["key"]),
                amount_cents=int(r["amount_cents"]),
            )
        )
    out.sort(key=lambda x: x.key)
    return tuple(out)


def get_funding_demand_money_view(
    funding_demand_ulid: str,
    *,
    as_of_iso: str | None = None,
) -> FundingDemandMoneyViewDTO:
    where = "finance_v2.get_funding_demand_money_view"
    try:
        provider = _load_provider(where)
        raw = provider(funding_demand_ulid, as_of_iso=as_of_iso)

        links = MoneyLinksDTO(
            income_journal_ulids=tuple(raw.get("income_journal_ulids") or ()),
            expense_journal_ulids=tuple(
                raw.get("expense_journal_ulids") or ()
            ),
            reserve_ulids=tuple(raw.get("reserve_ulids") or ()),
            encumbrance_ulids=tuple(raw.get("encumbrance_ulids") or ()),
        )

        return FundingDemandMoneyViewDTO(
            funding_demand_ulid=str(raw["funding_demand_ulid"]),
            received_cents=int(raw.get("received_cents") or 0),
            reserved_cents=int(raw.get("reserved_cents") or 0),
            encumbered_cents=int(raw.get("encumbered_cents") or 0),
            spent_cents=int(raw.get("spent_cents") or 0),
            received_by_fund=_to_money_by_key(raw.get("received_by_fund")),
            reserved_by_fund=_to_money_by_key(raw.get("reserved_by_fund")),
            encumbered_by_fund=_to_money_by_key(
                raw.get("encumbered_by_fund")
            ),
            spent_by_expense_kind=_to_money_by_key(
                raw.get("spent_by_expense_kind")
            ),
            income_by_income_kind=_to_money_by_key(
                raw.get("income_by_income_kind")
            ),
            links=links,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


# -----------------
# Old Paradigm
# below this line
# -----------------


def _require_str(name: str, value: str | None) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_ulid(name: str, value: str | None) -> str:
    v = _require_str(name, value)
    if len(v) != 26:
        raise ValueError(f"{name} must be a 26-char ULID")
    return v


def _require_int_ge(name: str, value: Any, minval: int = 0) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an int")
    if value < minval:
        raise ValueError(f"{name} must be >= {minval}")
    return value


# -----------------
# DTOs
# -----------------


class DonationDTO(TypedDict):
    """PII-free summary of a monetary donation journaled in Finance.

    Fields:
        id:
            ULID of the Journal entry that recorded the donation
            (or 'DRY-RUN' for simulations).
        sponsor_ulid:
            ULID of the Sponsor (as known by the Sponsors slice).
        fund_id:
            ULID of the fin_fund row used for this donation.
        happened_at_utc:
            ISO-8601 UTC timestamp string when the donation was recorded
            (as used for the Journal's period).
        amount_cents:
            Positive integer amount in cents.
        flags:
            Optional list of tags such as ['dry_run'] or policy-related
            markers in the future.

    This mirrors the object returned by
    app.slices.finance.services_journal.log_donation(...):
    journal ULID plus sponsor/fund/amount metadata and any flags.
    """

    id: str
    sponsor_ulid: str
    fund_id: str
    happened_at_utc: str
    amount_cents: int
    flags: []


class FundDTO(TypedDict):
    id: str
    name: str
    restriction_type: str  # 'unrestricted'|'temporarily_restricted'|'permanently_restricted'
    starts_on: NotRequired[str]
    expires_on: NotRequired[str]
    balance_cents: int


class GrantDTO(TypedDict):
    id: str
    fund_id: str
    sponsor_ulid: str
    amount_awarded_cents: int
    start_on: str
    end_on: str
    reporting_frequency: str
    # 'monthly'|'quarterly'|'semiannual'|'annual'|'end_of_term'
    allowable_categories: list[str]
    match_required_cents: int


class ProjectDTO(TypedDict):
    id: str
    name: str
    code: NotRequired[str]
    starts_on: NotRequired[str]
    ends_on: NotRequired[str]
    is_active: bool


class BudgetDTO(TypedDict):
    id: str
    fund_id: str
    project_id: str
    fiscal_period: str
    category: str
    amount_cents: int


class ReceiptDTO(TypedDict):
    id: str
    fund_id: str
    received_on: str
    source: str
    amount_cents: int
    instrument: NotRequired[str]


class ExpenseDTO(TypedDict):
    id: str
    fund_id: str
    project_id: str
    happened_at_utc: str
    vendor: str
    amount_cents: int
    expense_type: str
    approved_by_ulid: NotRequired[str | None]
    flags: NotRequired[list[str]]


class ReimbursementDTO(TypedDict):
    id: str
    grant_id: str
    submitted_on: str
    period_start: str
    period_end: str
    amount_cents: int
    status: str


# Reports
class ActivitiesReportDTO(TypedDict):
    period: str
    by_restriction: dict[
        str, dict[str, int]
    ]  # {'unrestricted': {'revenue_cents':..,'expense_cents':..,'change_net_assets_cents':..}, ...}
    by_fund: dict[
        str, dict[str, Any]
    ]  # fund_id -> {'name':..., 'restriction_type':..., 'revenue_cents':..., 'expense_cents':...}
    by_project: dict[
        str, dict[str, Any]
    ]  # project_id -> {'name':..., 'revenue_cents':..., 'expense_cents':...}


class ExpensePreviewDTO(TypedDict):
    """
    PII-free preview of a proposed expense.

    This is essentially a Governance SpendDecision, plus the
    Finance-oriented identifiers the caller used (fund_id, project_id).
    """

    fund_id: str
    project_id: str

    # straight from Governance:
    ok: bool
    requires_override: bool
    reason: str

    fund_archetype_key: str
    project_type_key: str | None
    period_label: str | None
    amount_cents: int
    cap_cents: int | None
    spent_cents: int | None
    remaining_cents: int | None


# -----------------
# Log Donation
# services_journal
# -----------------


def log_donation(
    *,
    sponsor_ulid: str,
    fund_id: str,
    happened_at_utc: str,
    amount_cents: int,
    bank_account_code: str | None = None,
    revenue_account_code: str | None = None,
    memo: str | None = None,
    external_ref_id: str | None = None,
    created_by_actor: str | None = None,
    source: str | None = None,
    flags: list[str] | None = None,
    dry_run: bool = False,
) -> DonationDTO:
    """Record a monetary donation in Finance.

    Thin contract wrapper around
    app.slices.finance.services_journal.log_donation(...).

    Responsibilities:
      * Light validation (ULIDs, strings, ints).
      * Shape arguments into a `payload` dict.
      * Delegate to the Finance slice service.
      * Map errors into a canonical ContractError via `_as_contract_error`.

    For full semantics, see:
      app.slices.finance.services_journal.log_donation
    """
    where = "finance_v2.log_donation"
    try:
        sponsor_ulid = _require_ulid("sponsor_ulid", sponsor_ulid)
        fund_id = _require_ulid("fund_id", fund_id)
        happened_at_utc = _require_str("happened_at_utc", happened_at_utc)
        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)

        if flags is not None and not isinstance(flags, list):
            raise ValueError("flags must be a list of strings")

        from app.slices.finance import services_journal as svc

        payload: dict = {
            "sponsor_ulid": sponsor_ulid,
            "fund_id": fund_id,
            "happened_at_utc": happened_at_utc,
            "amount_cents": amount_cents,
        }

        if bank_account_code is not None:
            payload["bank_account_code"] = bank_account_code
        if revenue_account_code is not None:
            payload["revenue_account_code"] = revenue_account_code
        if memo is not None:
            payload["memo"] = memo
        if external_ref_id is not None:
            payload["external_ref_ulid"] = external_ref_id
        if created_by_actor is not None:
            payload["created_by_actor"] = created_by_actor
        if source is not None:
            payload["source"] = source
        if flags:
            payload["flags"] = flags

        return svc.log_donation(payload=payload, dry_run=dry_run)

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Preview Expense
# Preview, no write
# -----------------


def preview_expense(
    *,
    fund_id: str,
    project_id: str,
    fund_archetype_key: str,
    project_type_key: str | None,
    amount_cents: int,
    period_label: str | None = None,
    current_spent_cents: int | None = None,
) -> ExpensePreviewDTO:
    """
    Contract entry point: preview an expense against Governance budget
    policy, without writing anything to the Journal.

    Responsibilities:
      * Validate argument shapes (ULIDs, strings, positive amount).
      * Delegate to governance_v2.preview_spend_decision using the
        supplied fund_archetype_key / project_type_key / period_label.
      * Return an ExpensePreviewDTO bundling the Governance decision
        with the original Finance identifiers (fund_id, project_id).

    NOTE:
      This function is a *lead-in* to ``log_expense``; it MUST NOT call
      ``log_expense`` or write any Journal entries. Callers are expected
      to:
        1) call preview_expense(...)
        2) decide based on ok / requires_override
        3) call log_expense(...) separately if appropriate.
    """
    where = "finance_v2.preview_expense"
    try:
        fund_id = _require_ulid("fund_id", fund_id)
        project_id = _require_ulid("project_id", project_id)
        fund_archetype_key = _require_str(
            "fund_archetype_key", fund_archetype_key
        )
        if project_type_key is not None:
            project_type_key = _require_str(
                "project_type_key", project_type_key
            )
        if period_label is not None:
            period_label = _require_str("period_label", period_label)

        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)
        if current_spent_cents is not None:
            current_spent_cents = _require_int_ge(
                "current_spent_cents", current_spent_cents, minval=0
            )

        from app.extensions.contracts import governance_v2 as gov

        spend_decision = gov.preview_spend_decision(
            fund_archetype_key=fund_archetype_key,
            project_type_key=project_type_key,
            amount_cents=amount_cents,
            period_label=period_label,
            current_spent_cents=current_spent_cents,
        )

        return ExpensePreviewDTO(
            fund_id=fund_id,
            project_id=project_id,
            ok=spend_decision["ok"],
            requires_override=spend_decision["requires_override"],
            reason=spend_decision["reason"],
            fund_archetype_key=spend_decision["fund_archetype_key"],
            project_type_key=spend_decision["project_type_key"],
            period_label=spend_decision["period_label"],
            amount_cents=spend_decision["amount_cents"],
            cap_cents=spend_decision["cap_cents"],
            spent_cents=spend_decision["spent_cents"],
            remaining_cents=spend_decision["remaining_cents"],
        )

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Log Expense
# Write to journal
# -----------------


def log_expense(
    *,
    fund_id: str,
    project_id: str,
    happened_at_utc: str,
    vendor: str,
    amount_cents: int,
    category: str,
    bank_account_code: str | None = None,
    expense_account_code: str | None = None,
    memo: str | None = None,
    external_ref_id: str | None = None,
    created_by_actor: str | None = None,
    source: str | None = None,
    dry_run: bool = False,
) -> ExpenseDTO:
    """
    Contract entry point for recording an **expense** against a fund+project.

    This function is a thin, versioned wrapper around the Finance slice’s
    ``services_journal.log_expense`` service.

    """
    where = "finance_v2.log_expense"
    try:
        fund_id = _require_ulid("fund_id", fund_id)
        project_id = _require_ulid("project_id", project_id)
        happened_at_utc = _require_str("happened_at_utc", happened_at_utc)
        vendor = _require_str("vendor", vendor)
        category = _require_str("category", category)
        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)

        from app.slices.finance import services_journal as svc

        payload: dict = {
            "fund_id": fund_id,
            "project_id": project_id,
            "happened_at_utc": happened_at_utc,
            "vendor": vendor,
            "category": category,
            "amount_cents": amount_cents,
        }

        if bank_account_code is not None:
            payload["bank_account_code"] = bank_account_code
        if expense_account_code is not None:
            payload["expense_account_code"] = expense_account_code
        if memo is not None:
            payload["memo"] = memo
        if external_ref_id is not None:
            # internal key name matches the Finance service and log_donation
            payload["external_ref_ulid"] = external_ref_id
        if created_by_actor is not None:
            payload["created_by_actor"] = created_by_actor
        if source is not None:
            payload["source"] = source

        return svc.log_expense(payload, dry_run=dry_run)

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Functions that need
# Lego standardization
# -----------------


# -----------------
# Record Receipt
# services_journal
# -----------------
def record_receipt(payload: dict) -> ReceiptDTO:
    # type: ignore[override]
    from app.slices.finance.services_journal import (
        record_receipt as _svc_record_receipt,
    )

    return _svc_record_receipt(payload)


# -----------------
# Create Fund
# services_funds
# -----------------


def create_fund(
    *,
    code: str,
    name: str,
    archetype_key: str,
    restriction_type: str,
    starts_on: str | None = None,
    expires_on: str | None = None,
    actor_ulid: str,
    request_id: str,
) -> FundDTO:
    """
    Create a new fund bucket.

    Thin contract wrapper; see
    app.slices.finance.services_funds.create_fund for details.
    """
    where = "finance_v2.create_fund"
    try:
        code = _require_str("code", code)
        name = _require_str("name", name)
        archetype_key = _require_str("archetype_key", archetype_key)
        restriction_type = _require_str("restriction_type", restriction_type)
        actor_ulid = _require_ulid("actor_ulid", actor_ulid)
        request_id = _require_str("request_id", request_id)

        from app.slices.finance import services_funds as svc

        payload: dict = {
            "code": code,
            "name": name,
            "archetype_key": archetype_key,
            "restriction_type": restriction_type,
            "starts_on": starts_on,
            "expires_on": expires_on,
            "actor_ulid": actor_ulid,
            "request_id": request_id,
        }
        return svc.create_fund(payload)

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Transfer
# services_funds
# -----------------


def transfer(payload: dict) -> dict:
    from app.slices.finance.services_funds import transfer as _svc_transfer

    return _svc_transfer(payload)


# -----------------
# Set Budget
# services_funds
# -----------------
def set_budget(payload: dict) -> BudgetDTO:
    from app.slices.finance.services_funds import (
        set_budget as _svc_set_budget,
    )

    return _svc_set_budget(payload)


# -----------------
# Get Fund Summary
# services_funds
# -----------------


def get_fund_summary(*, fund_ulid: str) -> FundDTO:
    """
    Contract entry point: fetch a summary for a single Fund.

    - Validates fund_ulid shape (26-char ULID).
    - Delegates to finance.services_funds.get_fund_summary.
    - Normalises any errors into ContractError via _as_contract_error().
    """
    where = "finance_v2.get_fund_summary"
    try:
        fund_ulid = _require_ulid("fund_ulid", fund_ulid)

        from app.slices.finance import services_funds as svc

        return svc.get_fund_summary(fund_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_funds(*, include_inactive: bool = False) -> list[FundDTO]:
    """
    Contract entry point: list all funds with their current balances.

    - Performs light argument normalisation.
    - Delegates to finance.services_funds.list_funds_with_balances.
    - Normalises any errors into ContractError via _as_contract_error().
    """
    where = "finance_v2.list_funds"
    try:
        include_inactive = bool(include_inactive)

        from app.slices.finance import services_funds as svc

        return svc.list_funds_with_balances(
            include_inactive=include_inactive,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Create Grant
# services_grants
# -----------------


def create_grant(
    *,
    fund_id: str,
    sponsor_ulid: str,
    amount_awarded_cents: int,
    start_on: str,
    end_on: str,
    reporting_frequency: str,
    allowable_categories: list[str] | None = None,
    match_required_cents: int = 0,
) -> GrantDTO:
    """
    Contract entry point: create a grant configuration in Finance.

    This is a thin, versioned wrapper around the Finance slice’s
    ``services_grants.create_grant`` service. It:

      * performs basic shape validation on arguments
        (ULIDs, non-empty strings, positive integers),
      * normalises the allowable_categories list,
      * delegates to ``app.slices.finance.services_grants.create_grant(...)``,
      * catches any errors from the slice and re-raises them as a
        :class:`ContractError` via :func:`_as_contract_error`.

    Policy questions (which sponsors may award which kinds of grants,
    caps, etc.) should be decided by Governance before calling this
    contract. This function only records the approved grant as Finance
    facts.
    """
    where = "finance_v2.create_grant"
    try:
        fund_id = _require_ulid("fund_id", fund_id)
        sponsor_ulid = _require_ulid("sponsor_ulid", sponsor_ulid)
        start_on = _require_str("start_on", start_on)
        end_on = _require_str("end_on", end_on)
        reporting_frequency = _require_str(
            "reporting_frequency", reporting_frequency
        )
        amount_awarded_cents = _require_int_ge(
            "amount_awarded_cents", amount_awarded_cents, minval=1
        )
        match_required_cents = _require_int_ge(
            "match_required_cents", match_required_cents, minval=0
        )

        cats: list[str] | None = None
        if allowable_categories is not None:
            if not isinstance(allowable_categories, (list, tuple)):
                raise ValueError(
                    "allowable_categories must be a list of strings"
                )
            cats = []
            for c in allowable_categories:
                if not isinstance(c, str):
                    raise ValueError(
                        "all allowable_categories entries must be strings"
                    )
                c_stripped = c.strip()
                if c_stripped:
                    cats.append(c_stripped)

        from app.slices.finance import services_grants as svc

        payload: dict[str, Any] = {
            "fund_id": fund_id,
            "sponsor_ulid": sponsor_ulid,
            "amount_awarded_cents": amount_awarded_cents,
            "start_on": start_on,
            "end_on": end_on,
            "reporting_frequency": reporting_frequency,
            "match_required_cents": match_required_cents,
        }
        if cats is not None:
            payload["allowable_categories"] = cats

        return svc.create_grant(payload)

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Submit Reimbursement
# services_grants
# -----------------


def submit_reimbursement(
    *,
    grant_id: str,
    submitted_on: str,
    period_start: str,
    period_end: str,
    amount_cents: int,
    status: str = "submitted",
    actor_ulid: str | None = None,
    request_id: str | None = None,
) -> ReimbursementDTO:
    """
    Contract entry point: record a reimbursement request against a Grant.

    This is a thin, versioned wrapper around the Finance slice’s
    ``submit_reimbursement`` service. It:

      * validates basic argument shapes (ULID, non-empty strings, amount),
      * keeps the status in a small whitelist,
      * delegates to ``app.slices.finance.services_grants.submit_reimbursement``,
      * normalises any underlying errors as :class:`ContractError`
        via :func:`_as_contract_error`.

    Money does **not** move here; this is paperwork-only. When a Sponsor
    actually pays, cash is recorded separately via
    :func:`finance_v2.log_donation`, typically referencing this
    reimbursement via an external_ref or flag.
    """
    where = "finance_v2.submit_reimbursement"
    try:
        grant_id = _require_ulid("grant_id", grant_id)
        submitted_on = _require_str("submitted_on", submitted_on)
        period_start = _require_str("period_start", period_start)
        period_end = _require_str("period_end", period_end)
        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)
        status = _require_str("status", status)

        allowed_status = {"draft", "submitted", "approved", "paid", "void"}
        if status not in allowed_status:
            raise ValueError(
                "status must be one of: draft|submitted|approved|paid|void"
            )

        from app.slices.finance import services_grants as svc

        payload: dict[str, Any] = {
            "grant_id": grant_id,
            "submitted_on": submitted_on,
            "period_start": period_start,
            "period_end": period_end,
            "amount_cents": amount_cents,
            "status": status,
        }
        if actor_ulid is not None:
            payload["actor_ulid"] = actor_ulid
        if request_id is not None:
            payload["request_id"] = request_id

        return svc.submit_reimbursement(payload)

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Mark Disbursement
# services_grants
# -----------------


def mark_disbursed(
    *,
    reimbursement_id: str,
    status: str = "paid",
    actor_ulid: str | None = None,
    request_id: str | None = None,
) -> ReimbursementDTO:
    """
    Contract entry point: mark a Grant reimbursement as disbursed.

    Thin, versioned wrapper around
    :func:`app.slices.finance.services_grants.mark_disbursed`.

    Behaviour:
      * validates argument shapes (ULID, non-empty status),
      * constrains status to {'paid', 'void'},
      * passes through actor_ulid / request_id for ledger attribution,
      * normalises any underlying errors as :class:`ContractError`.
    """
    where = "finance_v2.mark_disbursed"
    try:
        reimbursement_id = _require_ulid("reimbursement_id", reimbursement_id)
        status = _require_str("status", status)

        allowed_status = {"paid", "void"}
        if status not in allowed_status:
            raise ValueError(
                "status must be 'paid' or 'void' for mark_disbursed"
            )

        from app.slices.finance import services_grants as svc

        payload: dict[str, Any] = {
            "reimbursement_id": reimbursement_id,
            "status": status,
        }
        if actor_ulid is not None:
            payload["actor_ulid"] = actor_ulid
        if request_id is not None:
            payload["request_id"] = request_id

        return svc.mark_disbursed(payload)

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Prepare Grant Report
# services_grants
# -----------------


def prepare_grant_report(
    *,
    grant_id: str,
    period_start: str,
    period_end: str,
) -> dict:
    """
    Contract entry point for generating a grant-period report.

    For detailed behaviour and the eventual return shape, see
    :func:`app.slices.finance.services_grants.prepare_grant_report`.

    MVP note:
        The underlying service currently raises NotImplementedError;
        this contract is in place so callers can be wired later without
        changing signatures.
    """
    where = "finance_v2.prepare_grant_report"
    try:
        grant_id = _require_ulid("grant_id", grant_id)
        period_start = _require_str("period_start", period_start)
        period_end = _require_str("period_end", period_end)

        from app.slices.finance import services_grants as svc

        payload: dict[str, Any] = {
            "grant_id": grant_id,
            "period_start": period_start,
            "period_end": period_end,
        }
        return svc.prepare_grant_report(payload)

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Statement of Activities
# services_report
# -----------------


def statement_of_activities(period: str) -> ActivitiesReportDTO:
    """Forward to Finance slice report service.
    Excludes non-monetary stats; includes valued in-kind.
    """
    from app.slices.finance.services_report import (
        statement_of_activities as _svc_soa,
    )

    return _svc_soa(period)
