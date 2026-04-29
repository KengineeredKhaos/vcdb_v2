# app/extensions/contracts/finance_v2.py

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from app.extensions.errors import ContractError
from app.slices.finance.services_commitments import (
    encumber_funds as _encumber_funds,
)
from app.slices.finance.services_commitments import (
    reserve_funds as _reserve_funds,
)
from app.slices.finance.services_ops_float import (
    allocate_ops_float as _allocate_ops_float,
)
from app.slices.finance.services_ops_float import (
    forgive_ops_float as _forgive_ops_float,
)
from app.slices.finance.services_ops_float import (
    get_ops_float as _get_ops_float,
)
from app.slices.finance.services_ops_float import (
    get_ops_float_summary as _get_ops_float_summary,
)
from app.slices.finance.services_ops_float import (
    repay_ops_float as _repay_ops_float,
)
from app.slices.finance.services_semantic_posting import (
    post_expense as _post_expense,
)
from app.slices.finance.services_semantic_posting import (
    post_income as _post_income,
)

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


class DonationDTO(TypedDict):
    id: str
    sponsor_ulid: str
    fund_id: str
    happened_at_utc: str
    amount_cents: int
    flags: list[str]


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


@dataclass(frozen=True)
class FundingDemandExecutionTruthDTO:
    funding_demand_ulid: str
    received_cents: int
    reserved_cents: int
    encumbered_cents: int
    spent_cents: int
    remaining_open_cents: int
    funded_enough: bool
    support_source_posture: str
    received_by_fund: tuple[MoneyByKeyDTO, ...]
    reserved_by_fund: tuple[MoneyByKeyDTO, ...]
    encumbered_by_fund: tuple[MoneyByKeyDTO, ...]
    spent_by_expense_kind: tuple[MoneyByKeyDTO, ...]
    income_by_income_kind: tuple[MoneyByKeyDTO, ...]
    ops_float_incoming_open_by_fund: tuple[MoneyByKeyDTO, ...]
    ops_float_outgoing_open_by_fund: tuple[MoneyByKeyDTO, ...]
    income_journal_ulids: tuple[str, ...]
    expense_journal_ulids: tuple[str, ...]
    reserve_ulids: tuple[str, ...]
    encumbrance_ulids: tuple[str, ...]
    ops_float_ulids: tuple[str, ...]


@dataclass(frozen=True)
class FundingDemandGoNoGoDTO:
    funding_demand_ulid: str
    project_ulid: str | None
    go_nogo: str  # go | no_go
    escalate_to_admin: bool
    operator_message: str
    blocking_reason_codes: tuple[str, ...]
    blocking_scope_type: str | None
    blocking_scope_ulid: str | None
    blocking_scope_label: str | None


@dataclass(frozen=True)
class IncomePostRequestDTO:
    amount_cents: int
    happened_at_utc: str

    fund_code: str
    fund_label: str
    fund_restriction_type: str  # unrestricted|temporarily_restricted|...

    income_kind: str
    receipt_method: str  # bank|undeposited

    source: str
    source_ref_ulid: str | None = None

    funding_demand_ulid: str | None = None
    project_ulid: str | None = None

    payer_entity_ulid: str | None = None
    memo: str | None = None
    created_by_actor: str | None = None
    request_id: str | None = None

    dry_run: bool = False


@dataclass(frozen=True)
class ExpensePostRequestDTO:
    amount_cents: int
    happened_at_utc: str

    fund_code: str
    fund_label: str
    fund_restriction_type: str

    expense_kind: str
    payment_method: str  # bank|petty_cash|ap

    source: str
    source_ref_ulid: str | None = None

    funding_demand_ulid: str | None = None
    project_ulid: str | None = None

    payee_entity_ulid: str | None = None
    encumbrance_ulid: str | None = None
    memo: str | None = None
    created_by_actor: str | None = None
    request_id: str | None = None

    dry_run: bool = False


@dataclass(frozen=True)
class PostedDTO:
    id: str
    amount_cents: int
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReserveRequestDTO:
    funding_demand_ulid: str
    fund_code: str
    amount_cents: int
    source: str

    fund_label: str | None = None
    fund_restriction_type: str | None = None
    project_ulid: str | None = None
    source_ref_ulid: str | None = None
    memo: str | None = None
    actor_ulid: str | None = None
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class EncumbranceRequestDTO:
    funding_demand_ulid: str
    fund_code: str
    amount_cents: int
    source: str

    fund_label: str | None = None
    fund_restriction_type: str | None = None
    project_ulid: str | None = None
    source_ref_ulid: str | None = None
    memo: str | None = None
    decision_fingerprint: str | None = None
    actor_ulid: str | None = None
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class OpsFloatRequestDTO:
    source_funding_demand_ulid: str
    dest_funding_demand_ulid: str
    fund_code: str
    amount_cents: int
    support_mode: str

    source_project_ulid: str | None = None
    dest_project_ulid: str | None = None
    decision_fingerprint: str | None = None
    source_ref_ulid: str | None = None
    memo: str | None = None
    actor_ulid: str | None = None
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class OpsFloatSettleRequestDTO:
    parent_ops_float_ulid: str
    amount_cents: int
    source_ref_ulid: str | None = None
    memo: str | None = None
    actor_ulid: str | None = None
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class OpsFloatSummaryDTO:
    funding_demand_ulid: str
    incoming_open_cents: int
    outgoing_open_cents: int
    incoming_open_by_fund: tuple[MoneyByKeyDTO, ...]
    outgoing_open_by_fund: tuple[MoneyByKeyDTO, ...]
    ops_float_ulids: tuple[str, ...]


@dataclass(frozen=True)
class OpsFloatViewDTO:
    ops_float_ulid: str
    action: str
    support_mode: str
    source_funding_demand_ulid: str
    source_project_ulid: str | None
    dest_funding_demand_ulid: str
    dest_project_ulid: str | None
    fund_code: str
    amount_cents: int
    open_cents: int
    status: str
    parent_ops_float_ulid: str | None
    decision_fingerprint: str | None
    source_ref_ulid: str | None


@dataclass(frozen=True)
class EncumbranceViewDTO:
    encumbrance_ulid: str
    funding_demand_ulid: str
    project_ulid: str | None
    fund_code: str
    amount_cents: int
    relieved_cents: int
    open_cents: int
    status: str
    decision_fingerprint: str | None
    source_ref_ulid: str | None


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
          list[{"key": fund_code, "amount_cents": int}, ...]
      spent_by_expense_kind:
          list[{"key": expense_kind, "amount_cents": int}, ...]
      income_by_income_kind:
          list[{"key": income_kind, "amount_cents": int}, ...]

      income_journal_ulids, expense_journal_ulids, reserve_ulids,
      encumbrance_ulids
    """
    try:
        mod = importlib.import_module("app.slices.finance.services_dashboard")
        fn = mod.get_funding_demand_money_view
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


def _load_encumbrance_provider(where: str):
    try:
        mod = importlib.import_module("app.slices.finance.services_dashboard")
        fn = mod.get_encumbrance_view
        return fn
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            code="provider_missing",
            where=where,
            message=(
                "Finance provider missing: "
                "app.slices.finance.services_dashboard.get_encumbrance_view"
            ),
            http_status=500,
        ) from exc


def _load_go_nogo_provider(where: str):
    try:
        mod = importlib.import_module("app.slices.finance.services_dashboard")
        fn = mod.get_funding_demand_go_nogo
        return fn
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            code="provider_missing",
            where=where,
            message=(
                "Finance provider missing: "
                "app.slices.finance.services_dashboard.get_funding_demand_go_nogo"
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


def _bucket_sum(rows: tuple[MoneyByKeyDTO, ...]) -> int:
    return sum(int(r.amount_cents or 0) for r in rows or ())


def _support_source_posture(
    *,
    received_by_fund: tuple[MoneyByKeyDTO, ...],
    ops_float_incoming_open_by_fund: tuple[MoneyByKeyDTO, ...],
) -> str:
    sponsor_like = _bucket_sum(received_by_fund)
    ops_like = _bucket_sum(ops_float_incoming_open_by_fund)

    if sponsor_like > 0 and ops_like > 0:
        return "mixed"
    if ops_like > 0:
        return "ops_float_supported"
    if sponsor_like > 0:
        return "sponsor_funded"
    return "unfunded"


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


def get_funding_demand_execution_truth(
    funding_demand_ulid: str,
    *,
    goal_cents: int | None = None,
    as_of_iso: str | None = None,
) -> FundingDemandExecutionTruthDTO:
    where = "finance_v2.get_funding_demand_execution_truth"
    try:
        funding_demand_ulid = _require_ulid(
            "funding_demand_ulid",
            funding_demand_ulid,
        )
        if goal_cents is not None:
            goal_cents = _require_int_ge("goal_cents", goal_cents, 0)

        money = get_funding_demand_money_view(
            funding_demand_ulid,
            as_of_iso=as_of_iso,
        )
        ops = get_ops_float_summary(funding_demand_ulid)

        available_support_cents = int(money.reserved_cents or 0) + int(
            ops.incoming_open_cents or 0
        )
        remaining_open_cents = max(
            int(goal_cents or 0) - int(money.spent_cents or 0),
            0,
        )
        funded_enough = (
            goal_cents is not None
            and available_support_cents >= int(goal_cents)
        )

        return FundingDemandExecutionTruthDTO(
            funding_demand_ulid=funding_demand_ulid,
            received_cents=int(money.received_cents or 0),
            reserved_cents=int(money.reserved_cents or 0),
            encumbered_cents=int(money.encumbered_cents or 0),
            spent_cents=int(money.spent_cents or 0),
            remaining_open_cents=remaining_open_cents,
            funded_enough=funded_enough,
            support_source_posture=_support_source_posture(
                received_by_fund=money.received_by_fund,
                ops_float_incoming_open_by_fund=ops.incoming_open_by_fund,
            ),
            received_by_fund=money.received_by_fund,
            reserved_by_fund=money.reserved_by_fund,
            encumbered_by_fund=money.encumbered_by_fund,
            spent_by_expense_kind=money.spent_by_expense_kind,
            income_by_income_kind=money.income_by_income_kind,
            ops_float_incoming_open_by_fund=ops.incoming_open_by_fund,
            ops_float_outgoing_open_by_fund=ops.outgoing_open_by_fund,
            income_journal_ulids=tuple(
                money.links.income_journal_ulids or ()
            ),
            expense_journal_ulids=tuple(
                money.links.expense_journal_ulids or ()
            ),
            reserve_ulids=tuple(money.links.reserve_ulids or ()),
            encumbrance_ulids=tuple(money.links.encumbrance_ulids or ()),
            ops_float_ulids=tuple(ops.ops_float_ulids or ()),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def get_funding_demand_go_nogo(
    funding_demand_ulid: str,
    *,
    project_ulid: str | None = None,
) -> FundingDemandGoNoGoDTO:
    """Return Finance integrity gate for staff-facing demand processing.

    Canon note for Future Dev:
      This is intentionally blunt. Staff does not need Finance internals.
      Staff needs a trusted GO / NO GO answer for whether the funding stream
      is sufficiently clean to allow demand processing right now.

      This is not a funding sufficiency or policy decision seam.
    """
    where = "finance_v2.get_funding_demand_go_nogo"
    try:
        funding_demand_ulid = _require_ulid(
            "funding_demand_ulid",
            funding_demand_ulid,
        )
        if project_ulid is not None:
            project_ulid = _require_ulid("project_ulid", project_ulid)

        provider = _load_go_nogo_provider(where)
        raw = provider(
            funding_demand_ulid,
            project_ulid=project_ulid,
        )
        return FundingDemandGoNoGoDTO(
            funding_demand_ulid=str(raw["funding_demand_ulid"]),
            project_ulid=raw.get("project_ulid"),
            go_nogo=str(raw["go_nogo"]),
            escalate_to_admin=bool(raw["escalate_to_admin"]),
            operator_message=str(raw["operator_message"]),
            blocking_reason_codes=tuple(raw.get("blocking_reason_codes") or ()),
            blocking_scope_type=raw.get("blocking_scope_type"),
            blocking_scope_ulid=raw.get("blocking_scope_ulid"),
            blocking_scope_label=raw.get("blocking_scope_label"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def get_encumbrance(encumbrance_ulid: str) -> EncumbranceViewDTO:
    where = "finance_v2.get_encumbrance"
    try:
        provider = _load_encumbrance_provider(where)
        raw = provider(encumbrance_ulid)
        return EncumbranceViewDTO(
            encumbrance_ulid=str(raw["encumbrance_ulid"]),
            funding_demand_ulid=str(raw["funding_demand_ulid"]),
            project_ulid=raw.get("project_ulid"),
            fund_code=str(raw["fund_code"]),
            amount_cents=int(raw.get("amount_cents") or 0),
            relieved_cents=int(raw.get("relieved_cents") or 0),
            open_cents=int(raw.get("open_cents") or 0),
            status=str(raw.get("status") or "unknown"),
            decision_fingerprint=raw.get("decision_fingerprint"),
            source_ref_ulid=raw.get("source_ref_ulid"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def post_income(req: IncomePostRequestDTO) -> PostedDTO:
    where = "finance_v2.post_income"
    try:
        out = _post_income(
            {
                "amount_cents": req.amount_cents,
                "happened_at_utc": req.happened_at_utc,
                "fund_code": req.fund_code,
                "fund_label": req.fund_label,
                "fund_restriction_type": req.fund_restriction_type,
                "income_kind": req.income_kind,
                "receipt_method": req.receipt_method,
                "source": req.source,
                "source_ref_ulid": req.source_ref_ulid,
                "funding_demand_ulid": req.funding_demand_ulid,
                "project_ulid": req.project_ulid,
                "payer_entity_ulid": req.payer_entity_ulid,
                "memo": req.memo,
                "created_by_actor": req.created_by_actor,
                "request_id": req.request_id,
            },
            dry_run=req.dry_run,
        )
        return PostedDTO(
            id=str(out["id"]),
            amount_cents=int(out.get("amount_cents") or 0),
            flags=tuple(out.get("flags") or ()),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def post_expense(req: ExpensePostRequestDTO) -> PostedDTO:
    where = "finance_v2.post_expense"
    try:
        out = _post_expense(
            {
                "amount_cents": req.amount_cents,
                "happened_at_utc": req.happened_at_utc,
                "fund_code": req.fund_code,
                "fund_label": req.fund_label,
                "fund_restriction_type": req.fund_restriction_type,
                "expense_kind": req.expense_kind,
                "payment_method": req.payment_method,
                "source": req.source,
                "source_ref_ulid": req.source_ref_ulid,
                "funding_demand_ulid": req.funding_demand_ulid,
                "project_ulid": req.project_ulid,
                "payee_entity_ulid": req.payee_entity_ulid,
                "encumbrance_ulid": req.encumbrance_ulid,
                "memo": req.memo,
                "created_by_actor": req.created_by_actor,
                "request_id": req.request_id,
            },
            dry_run=req.dry_run,
        )
        return PostedDTO(
            id=str(out["id"]),
            amount_cents=int(out.get("amount_cents") or 0),
            flags=tuple(out.get("flags") or ()),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def reserve_funds(req: ReserveRequestDTO) -> PostedDTO:
    where = "finance_v2.reserve_funds"
    try:
        out = _reserve_funds(
            {
                "funding_demand_ulid": req.funding_demand_ulid,
                "fund_code": req.fund_code,
                "amount_cents": req.amount_cents,
                "source": req.source,
                "fund_label": req.fund_label,
                "fund_restriction_type": req.fund_restriction_type,
                "project_ulid": req.project_ulid,
                "source_ref_ulid": req.source_ref_ulid,
                "memo": req.memo,
                "actor_ulid": req.actor_ulid,
                "request_id": req.request_id,
            },
            dry_run=req.dry_run,
        )
        return PostedDTO(
            id=str(out["id"]),
            amount_cents=int(out.get("amount_cents") or 0),
            flags=("reserved",) if not req.dry_run else ("dry_run",),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def encumber_funds(req: EncumbranceRequestDTO) -> PostedDTO:
    where = "finance_v2.encumber_funds"
    try:
        out = _encumber_funds(
            {
                "funding_demand_ulid": req.funding_demand_ulid,
                "fund_code": req.fund_code,
                "amount_cents": req.amount_cents,
                "source": req.source,
                "fund_label": req.fund_label,
                "fund_restriction_type": req.fund_restriction_type,
                "project_ulid": req.project_ulid,
                "source_ref_ulid": req.source_ref_ulid,
                "memo": req.memo,
                "decision_fingerprint": req.decision_fingerprint,
                "actor_ulid": req.actor_ulid,
                "request_id": req.request_id,
            },
            dry_run=req.dry_run,
        )
        return PostedDTO(
            id=str(out["id"]),
            amount_cents=int(out.get("amount_cents") or 0),
            flags=("encumbered",) if not req.dry_run else ("dry_run",),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def allocate_ops_float(req: OpsFloatRequestDTO) -> PostedDTO:
    where = "finance_v2.allocate_ops_float"
    try:
        out = _allocate_ops_float(
            {
                "source_funding_demand_ulid": req.source_funding_demand_ulid,
                "source_project_ulid": req.source_project_ulid,
                "dest_funding_demand_ulid": req.dest_funding_demand_ulid,
                "dest_project_ulid": req.dest_project_ulid,
                "fund_code": req.fund_code,
                "amount_cents": req.amount_cents,
                "support_mode": req.support_mode,
                "decision_fingerprint": req.decision_fingerprint,
                "source_ref_ulid": req.source_ref_ulid,
                "memo": req.memo,
                "actor_ulid": req.actor_ulid,
                "request_id": req.request_id,
            },
            dry_run=req.dry_run,
        )
        return PostedDTO(
            id=str(out["id"]),
            amount_cents=int(out["amount_cents"]),
            flags=(str(out.get("support_mode") or ""),),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def repay_ops_float(req: OpsFloatSettleRequestDTO) -> PostedDTO:
    where = "finance_v2.repay_ops_float"
    try:
        out = _repay_ops_float(
            {
                "parent_ops_float_ulid": req.parent_ops_float_ulid,
                "amount_cents": req.amount_cents,
                "source_ref_ulid": req.source_ref_ulid,
                "memo": req.memo,
                "actor_ulid": req.actor_ulid,
                "request_id": req.request_id,
            },
            dry_run=req.dry_run,
        )
        return PostedDTO(
            id=str(out["id"]),
            amount_cents=int(out["amount_cents"]),
            flags=(str(out.get("support_mode") or ""),),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def forgive_ops_float(req: OpsFloatSettleRequestDTO) -> PostedDTO:
    where = "finance_v2.forgive_ops_float"
    try:
        out = _forgive_ops_float(
            {
                "parent_ops_float_ulid": req.parent_ops_float_ulid,
                "amount_cents": req.amount_cents,
                "source_ref_ulid": req.source_ref_ulid,
                "memo": req.memo,
                "actor_ulid": req.actor_ulid,
                "request_id": req.request_id,
            },
            dry_run=req.dry_run,
        )
        return PostedDTO(
            id=str(out["id"]),
            amount_cents=int(out["amount_cents"]),
            flags=(str(out.get("support_mode") or ""),),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_ops_float_summary(
    funding_demand_ulid: str,
) -> OpsFloatSummaryDTO:
    where = "finance_v2.get_ops_float_summary"
    try:
        raw = _get_ops_float_summary(funding_demand_ulid)
        return OpsFloatSummaryDTO(
            funding_demand_ulid=str(raw["funding_demand_ulid"]),
            incoming_open_cents=int(raw["incoming_open_cents"]),
            outgoing_open_cents=int(raw["outgoing_open_cents"]),
            incoming_open_by_fund=_to_money_by_key(
                raw.get("incoming_open_by_fund")
            ),
            outgoing_open_by_fund=_to_money_by_key(
                raw.get("outgoing_open_by_fund")
            ),
            ops_float_ulids=tuple(raw.get("ops_float_ulids") or ()),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_ops_float(ops_float_ulid: str) -> OpsFloatViewDTO:
    where = "finance_v2.get_ops_float"
    try:
        raw = _get_ops_float(ops_float_ulid)
        return OpsFloatViewDTO(
            ops_float_ulid=str(raw["ops_float_ulid"]),
            action=str(raw["action"]),
            support_mode=str(raw["support_mode"]),
            source_funding_demand_ulid=str(raw["source_funding_demand_ulid"]),
            source_project_ulid=raw.get("source_project_ulid"),
            dest_funding_demand_ulid=str(raw["dest_funding_demand_ulid"]),
            dest_project_ulid=raw.get("dest_project_ulid"),
            fund_code=str(raw["fund_code"]),
            amount_cents=int(raw["amount_cents"]),
            open_cents=int(raw["open_cents"]),
            status=str(raw["status"]),
            parent_ops_float_ulid=raw.get("parent_ops_float_ulid"),
            decision_fingerprint=raw.get("decision_fingerprint"),
            source_ref_ulid=raw.get("source_ref_ulid"),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc  # -----------------


# -----------------
# Retired Legacy Surfaces
# -----------------


def _retired_surface(name: str, replacement: str) -> ContractError:
    return ContractError(
        code="retired",
        where=f"finance_v2.{name}",
        message=(f"{name} is retired. Use {replacement} instead."),
        http_status=410,
    )


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
    raise _retired_surface(
        "log_donation",
        "post_income(...) from the Sponsors funding realization flow",
    )


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
    raise _retired_surface(
        "preview_expense",
        "Governance policy preview contract or Finance semantic posting helpers",
    )


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
    raise _retired_surface(
        "log_expense",
        "post_expense(...) from the Calendar spend / disbursement flow",
    )


# -----------------
# Functions that need
# Lego standardization
# -----------------


# -----------------
# Record Receipt
# services_journal
# -----------------
def record_receipt(payload: dict) -> ReceiptDTO:
    raise _retired_surface(
        "finance_v2.record_receipt",
        "post_income(...) from the Sponsors funding realization flow",
    )


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
# Create Grant Award
# services_grants
# -----------------


def create_grant_award(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Contract seam for the richer grant-acceptance payload.

    This keeps the original ``create_grant(...)`` wrapper intact while
    giving Sponsors a contract-only way to create the newer Finance
    ``Grant`` record using ``fund_code`` and the optional grant-specific
    fields added during the hardening pass.
    """
    where = "finance_v2.create_grant_award"
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        from app.slices.finance import services_grants as svc

        return svc.create_grant(payload)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Record Disbursement
# services_grants
# -----------------


def record_disbursement(payload: dict[str, Any]) -> dict[str, Any]:
    """Contract seam for Finance cash-out tracking."""
    where = "finance_v2.record_disbursement"
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        from app.slices.finance import services_grants as svc

        return svc.record_disbursement(payload)
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


__all__ = [
    "FundingDemandMoneyViewDTO",
    "FundingDemandExecutionTruthDTO",
    "FundingDemandGoNoGoDTO",
    "IncomePostRequestDTO",
    "ExpensePostRequestDTO",
    "PostedDTO",
    "ReserveRequestDTO",
    "EncumbranceRequestDTO",
    "OpsFloatRequestDTO",
    "OpsFloatSettleRequestDTO",
    "OpsFloatSummaryDTO",
    "OpsFloatViewDTO",
    "EncumbranceViewDTO",
    "DonationDTO",
    "ExpenseDTO",
    "ReceiptDTO",
    "get_funding_demand_money_view",
    "get_funding_demand_execution_truth",
    "get_funding_demand_go_nogo",
    "get_encumbrance",
    "post_income",
    "post_expense",
    "reserve_funds",
    "encumber_funds",
    "allocate_ops_float",
    "repay_ops_float",
    "forgive_ops_float",
    "get_ops_float_summary",
    "get_ops_float",
    "create_grant",
    "submit_reimbursement",
    "mark_disbursed",
    "prepare_grant_report",
    "create_grant_award",
    "record_disbursement",
    "statement_of_activities",
]
