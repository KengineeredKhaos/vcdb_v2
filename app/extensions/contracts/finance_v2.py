# app/extensions/contracts/finance_v2.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.extensions.contracts.errors import ContractError


# ---------- DTOs ----------
@dataclass
class FundDTO:
    id: str
    name: str
    restriction_type: str  # 'unrestricted'|'temporarily_restricted'|'permanently_restricted'
    starts_on: Optional[str]
    expires_on: Optional[str]
    balance_cents: int = 0


@dataclass
class GrantDTO:
    id: str
    fund_id: str
    sponsor_ulid: str
    amount_awarded_cents: int
    start_on: str
    end_on: str
    reporting_frequency: str  # 'monthly'|'quarterly'|'semiannual'|'annual'|'end_of_term'
    allowable_categories: List[str]
    match_required_cents: int = 0


@dataclass
class ProjectDTO:
    id: str
    name: str
    code: Optional[str]
    starts_on: Optional[str]
    ends_on: Optional[str]
    is_active: bool = True


@dataclass
class BudgetDTO:
    id: str
    fund_id: str
    project_id: str
    fiscal_period: str
    category: str
    amount_cents: int


@dataclass
class ReceiptDTO:
    id: str
    fund_id: str
    received_on: str
    source: str
    amount_cents: int
    instrument: Optional[str] = None


@dataclass
class ExpenseDTO:
    id: str
    fund_id: str
    project_id: str
    occurred_on: str
    vendor: str
    amount_cents: int
    category: str
    approved_by_ulid: Optional[str] = None
    flags: List[str] = None


@dataclass
class ReimbursementDTO:
    id: str
    grant_id: str
    submitted_on: str
    period_start: str
    period_end: str
    amount_cents: int
    status: str


# Reports
@dataclass
class ActivitiesReportDTO:
    period: str
    by_restriction: Dict[
        str, Dict[str, int]
    ]  # {'unrestricted': {'revenue_cents':..,'expense_cents':..,'change_net_assets_cents':..}, ...}
    by_fund: Dict[
        str, Dict[str, Any]
    ]  # fund_id -> {'name':..., 'restriction_type':..., 'revenue_cents':..., 'expense_cents':...}
    by_project: Dict[
        str, Dict[str, Any]
    ]  # project_id -> {'name':..., 'revenue_cents':..., 'expense_cents':...}


# ---------- Exceptions (contract-scoped) ----------
class FinanceContractError(Exception):
    pass


class RestrictionViolation(FinanceContractError):
    ...


class BudgetExceeded(FinanceContractError):
    ...


class CategoryNotAllowed(FinanceContractError):
    ...


class ApprovalRequired(FinanceContractError):
    ...


class DocumentationMissing(FinanceContractError):
    ...


class ValuationRequired(FinanceContractError):
    ...


# ---------- Requests (type hints only; define as dataclasses later if you prefer) ----------
# These are intentionally minimal so you can wire them as thin facades over slice services.


def log_expense(payload: dict, *, dry_run: bool = False) -> ExpenseDTO:  # type: ignore[override]
    """Contract entry point: validate & delegate to Finance slice services.
    Required keys in payload: fund_id, project_id, occurred_on, vendor, amount_cents, category.
    May raise: RestrictionViolation, BudgetExceeded, CategoryNotAllowed, ApprovalRequired, DocumentationMissing
    """
    from app.slices.finance.services import (
        log_expense as _svc_log_expense,
    )  # lazy import to avoid cross-slice cycles

    return _svc_log_expense(payload, dry_run=dry_run)


def record_receipt(payload: dict) -> ReceiptDTO:  # type: ignore[override]
    from app.slices.finance.services import (
        record_receipt as _svc_record_receipt,
    )

    return _svc_record_receipt(payload)


def create_fund(payload: dict) -> FundDTO:
    from app.slices.finance.services import create_fund as _svc_create_fund

    return _svc_create_fund(payload)


def transfer(payload: dict) -> dict:
    from app.slices.finance.services import transfer as _svc_transfer

    return _svc_transfer(payload)


def create_grant(payload: dict) -> GrantDTO:
    from app.slices.finance.services import create_grant as _svc_create_grant

    return _svc_create_grant(payload)


def set_budget(payload: dict) -> BudgetDTO:
    from app.slices.finance.services import set_budget as _svc_set_budget

    return _svc_set_budget(payload)


def prepare_grant_report(payload: dict) -> dict:
    from app.slices.finance.services import (
        prepare_grant_report as _svc_prepare,
    )

    return _svc_prepare(payload)


def submit_reimbursement(payload: dict) -> ReimbursementDTO:
    from app.slices.finance.services import (
        submit_reimbursement as _svc_submit,
    )

    return _svc_submit(payload)


def mark_disbursed(payload: dict) -> ReimbursementDTO:
    from app.slices.finance.services import mark_disbursed as _svc_mark

    return _svc_mark(payload)


def statement_of_activities(period: str) -> ActivitiesReportDTO:
    """Forward to Finance slice report service.
    Excludes non-monetary stats; includes valued in-kind.
    """
    from app.slices.finance.services_report import (
        statement_of_activities as _svc_soa,
    )

    return _svc_soa(period)


def get_fund_summary(fund_ulid: str) -> FundDTO:
    from app.slices.finance.services import get_fund_summary as _svc

    try:
        return _svc(fund_ulid)
    except Exception as e:  # ideally a FinanceError subclass
        raise ContractError(
            "finance.fund_not_found",
            f"Fund {fund_ulid} not found",
            {"fund_ulid": fund_ulid},
        ) from e
