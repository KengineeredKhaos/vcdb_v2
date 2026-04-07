from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import (
    DISBURSEMENT_METHODS,
    DISBURSEMENT_STATUSES,
    GRANT_FUNDING_MODES,
    GRANT_REPORTING_FREQUENCIES,
    GRANT_STATUSES,
    REIMBURSEMENT_LINE_STATUSES,
    REIMBURSEMENT_STATUSES,
    Disbursement,
    Encumbrance,
    Fund,
    Grant,
    Journal,
    JournalLine,
    Reimbursement,
    ReimbursementLine,
    Reserve,
)


def _require_str(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _require_int_ge(name: str, value: Any, minimum: int = 0) -> int:
    try:
        number = int(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{name} must be an integer") from exc
    if number < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return number


def _normalize_key_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raise ValueError("allowable_expense_kinds must be list-like")

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    return sorted(cleaned)


def _normalize_restriction(value: Any) -> str:
    key = str(value or "unrestricted").strip().lower()
    mapping = {
        "unrestricted": "unrestricted",
        "temp": "temporarily_restricted",
        "temporary": "temporarily_restricted",
        "temporarily_restricted": "temporarily_restricted",
        "perm": "permanently_restricted",
        "permanent": "permanently_restricted",
        "permanently_restricted": "permanently_restricted",
    }
    out = mapping.get(key, key)
    if out not in {
        "unrestricted",
        "temporarily_restricted",
        "permanently_restricted",
    }:
        raise ValueError("invalid restriction_type")
    return out


def _fund_by_ulid(fund_ulid: str | None) -> Fund | None:
    if not fund_ulid:
        return None
    return db.session.get(Fund, fund_ulid)


def _fund_by_code(fund_code: str | None) -> Fund | None:
    if not fund_code:
        return None
    return db.session.execute(
        select(Fund).where(Fund.code == fund_code)
    ).scalar_one_or_none()


def _resolve_fund(payload: dict[str, Any]) -> tuple[str, Fund | None]:
    fund_code = _optional_str(payload.get("fund_code"))
    fund_id = _optional_str(payload.get("fund_id"))

    if fund_code:
        return fund_code, _fund_by_code(fund_code)

    if fund_id:
        fund = _fund_by_ulid(fund_id)
        if fund is None:
            raise LookupError(f"fund not found: {fund_id}")
        return fund.code, fund

    raise ValueError("fund_code is required")


def _date_required(name: str, value: Any) -> str:
    text = _require_str(name, value)
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise ValueError(f"{name} must be YYYY-MM-DD")
    return text


def _journal_total_for_codes(
    *,
    grant_ulid: str,
    period_start: str,
    period_end: str,
    prefixes: tuple[str, ...],
    invert_sign: bool = False,
) -> int:
    rows = db.session.execute(
        select(JournalLine, Journal)
        .join(Journal, Journal.ulid == JournalLine.journal_ulid)
        .where(JournalLine.grant_ulid == grant_ulid)
        .where(Journal.happened_at_utc >= period_start)
        .where(Journal.happened_at_utc <= f"{period_end}T23:59:59Z")
    ).all()

    total = 0
    for line, _journal in rows:
        if not line.account_code.startswith(prefixes):
            continue
        amount = int(line.amount_cents or 0)
        total += -amount if invert_sign else amount
    return total


@dataclass(frozen=True)
class GrantView:
    id: str
    fund_code: str
    fund_id: str | None
    restriction_type: str
    sponsor_ulid: str
    project_ulid: str | None
    award_number: str | None
    award_name: str
    funding_mode: str
    amount_awarded_cents: int
    match_required_cents: int
    start_on: str
    end_on: str
    reporting_frequency: str
    program_income_allowed: bool
    allowable_expense_kinds: tuple[str, ...]
    conditions_summary: str | None
    source_document_ref: str | None
    status: str
    notes: str | None


@dataclass(frozen=True)
class ReimbursementView:
    id: str
    grant_id: str
    project_ulid: str
    funding_demand_ulid: str | None
    claim_number: str | None
    submitted_on: str | None
    period_start: str
    period_end: str
    claimed_amount_cents: int
    approved_amount_cents: int
    received_amount_cents: int
    status: str
    notes: str | None


@dataclass(frozen=True)
class DisbursementView:
    id: str
    expense_journal_ulid: str
    grant_ulid: str | None
    project_ulid: str
    funding_demand_ulid: str | None
    amount_cents: int
    disbursed_on: str
    method: str
    reference: str | None
    status: str
    notes: str | None


def _grant_view(row: Grant, *, fund: Fund | None = None) -> dict[str, Any]:
    fund = fund or _fund_by_code(row.fund_code)
    view = GrantView(
        id=row.ulid,
        fund_code=row.fund_code,
        fund_id=getattr(fund, "ulid", None),
        restriction_type=row.restriction_type,
        sponsor_ulid=row.sponsor_ulid,
        project_ulid=row.project_ulid,
        award_number=row.award_number,
        award_name=row.award_name,
        funding_mode=row.funding_mode,
        amount_awarded_cents=int(row.amount_awarded_cents or 0),
        match_required_cents=int(row.match_required_cents or 0),
        start_on=row.start_on,
        end_on=row.end_on,
        reporting_frequency=row.reporting_frequency,
        program_income_allowed=bool(row.program_income_allowed),
        allowable_expense_kinds=tuple(row.allowable_expense_kinds),
        conditions_summary=row.conditions_summary,
        source_document_ref=row.source_document_ref,
        status=row.status,
        notes=row.notes,
    )
    return asdict(view)


def _reimbursement_view(row: Reimbursement) -> dict[str, Any]:
    view = ReimbursementView(
        id=row.ulid,
        grant_id=row.grant_ulid,
        project_ulid=row.project_ulid,
        funding_demand_ulid=row.funding_demand_ulid,
        claim_number=row.claim_number,
        submitted_on=row.submitted_on,
        period_start=row.period_start,
        period_end=row.period_end,
        claimed_amount_cents=int(row.claimed_amount_cents or 0),
        approved_amount_cents=int(row.approved_amount_cents or 0),
        received_amount_cents=int(row.received_amount_cents or 0),
        status=row.status,
        notes=row.notes,
    )
    out = asdict(view)
    out["amount_cents"] = out["claimed_amount_cents"]
    return out


def _disbursement_view(row: Disbursement) -> dict[str, Any]:
    return asdict(
        DisbursementView(
            id=row.ulid,
            expense_journal_ulid=row.expense_journal_ulid,
            grant_ulid=row.grant_ulid,
            project_ulid=row.project_ulid,
            funding_demand_ulid=row.funding_demand_ulid,
            amount_cents=int(row.amount_cents or 0),
            disbursed_on=row.disbursed_on,
            method=row.method,
            reference=row.reference,
            status=row.status,
            notes=row.notes,
        )
    )


def create_grant(payload: dict[str, Any]) -> dict[str, Any]:
    fund_code, fund = _resolve_fund(payload)

    sponsor_ulid = _require_str("sponsor_ulid", payload.get("sponsor_ulid"))
    award_name = _optional_str(payload.get("award_name"))
    if not award_name:
        award_name = _optional_str(payload.get("award_number"))
        if award_name:
            award_name = f"Grant {award_name}"
        else:
            award_name = f"Grant {fund_code}"

    amount_awarded_cents = _require_int_ge(
        "amount_awarded_cents",
        payload.get("amount_awarded_cents"),
        1,
    )
    start_on = _date_required("start_on", payload.get("start_on"))
    end_on = _date_required("end_on", payload.get("end_on"))
    reporting_frequency = _require_str(
        "reporting_frequency",
        payload.get("reporting_frequency"),
    )
    if reporting_frequency not in GRANT_REPORTING_FREQUENCIES:
        raise ValueError("invalid reporting_frequency")

    funding_mode = _optional_str(payload.get("funding_mode"))
    funding_mode = funding_mode or "reimbursement"
    if funding_mode not in GRANT_FUNDING_MODES:
        raise ValueError("invalid funding_mode")

    restriction_type = payload.get("restriction_type")
    if restriction_type is None and fund is not None:
        restriction_type = fund.restriction
    restriction_type = _normalize_restriction(restriction_type)

    grant = Grant(
        fund_code=fund_code,
        restriction_type=restriction_type,
        sponsor_ulid=sponsor_ulid,
        project_ulid=_optional_str(payload.get("project_ulid")),
        award_number=_optional_str(payload.get("award_number")),
        award_name=award_name,
        funding_mode=funding_mode,
        amount_awarded_cents=amount_awarded_cents,
        match_required_cents=_require_int_ge(
            "match_required_cents",
            payload.get("match_required_cents", 0),
            0,
        ),
        start_on=start_on,
        end_on=end_on,
        reporting_frequency=reporting_frequency,
        program_income_allowed=bool(
            payload.get("program_income_allowed", False)
        ),
        conditions_summary=_optional_str(
            payload.get("conditions_summary")
        ),
        source_document_ref=_optional_str(
            payload.get("source_document_ref")
        ),
        status=_optional_str(payload.get("status")) or "draft",
        notes=_optional_str(payload.get("notes")),
    )
    if grant.status not in GRANT_STATUSES:
        raise ValueError("invalid grant status")
    grant.allowable_expense_kinds = _normalize_key_list(
        payload.get("allowable_expense_kinds")
        or payload.get("allowable_categories")
    )

    db.session.add(grant)
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="grant_created",
        request_id=str(payload.get("request_id") or grant.ulid),
        actor_ulid=payload.get("actor_ulid"),
        target_ulid=grant.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "fund_code": grant.fund_code,
            "project_ulid": grant.project_ulid,
            "sponsor_ulid": grant.sponsor_ulid,
        },
        changed={
            "fields": [
                "fund_code",
                "restriction_type",
                "project_ulid",
                "award_number",
                "award_name",
                "funding_mode",
                "amount_awarded_cents",
                "match_required_cents",
                "start_on",
                "end_on",
                "reporting_frequency",
                "program_income_allowed",
                "allowable_expense_kinds_raw",
                "conditions_summary",
                "source_document_ref",
                "status",
                "notes",
            ]
        },
        chain_key="finance.grant",
    )
    return _grant_view(grant, fund=fund)


def submit_reimbursement(payload: dict[str, Any]) -> dict[str, Any]:
    grant_ulid = _optional_str(payload.get("grant_ulid"))
    if not grant_ulid:
        grant_ulid = _optional_str(payload.get("grant_id"))
    if not grant_ulid:
        raise ValueError("grant_ulid is required")

    grant = db.session.get(Grant, grant_ulid)
    if grant is None:
        raise LookupError(f"grant not found: {grant_ulid}")

    project_ulid = _optional_str(payload.get("project_ulid"))
    project_ulid = project_ulid or grant.project_ulid
    if not project_ulid:
        raise ValueError("project_ulid is required")

    status = _optional_str(payload.get("status")) or "submitted"
    if status not in REIMBURSEMENT_STATUSES:
        raise ValueError("invalid reimbursement status")

    claimed_amount_cents = payload.get("claimed_amount_cents")
    if claimed_amount_cents is None:
        claimed_amount_cents = payload.get("amount_cents")
    claimed_amount_cents = _require_int_ge(
        "claimed_amount_cents",
        claimed_amount_cents,
        1,
    )

    approved_amount_cents = _require_int_ge(
        "approved_amount_cents",
        payload.get("approved_amount_cents", 0),
        0,
    )
    received_amount_cents = _require_int_ge(
        "received_amount_cents",
        payload.get("received_amount_cents", 0),
        0,
    )
    if approved_amount_cents > claimed_amount_cents:
        raise ValueError("approved_amount_cents exceeds claimed")
    if received_amount_cents > approved_amount_cents:
        raise ValueError("received_amount_cents exceeds approved")

    row = Reimbursement(
        grant_ulid=grant.ulid,
        project_ulid=project_ulid,
        funding_demand_ulid=_optional_str(
            payload.get("funding_demand_ulid")
        ),
        claim_number=_optional_str(payload.get("claim_number")),
        period_start=_date_required(
            "period_start", payload.get("period_start")
        ),
        period_end=_date_required("period_end", payload.get("period_end")),
        submitted_on=_optional_str(payload.get("submitted_on")),
        decided_on=_optional_str(payload.get("decided_on")),
        received_on=_optional_str(payload.get("received_on")),
        claimed_amount_cents=claimed_amount_cents,
        approved_amount_cents=approved_amount_cents,
        received_amount_cents=received_amount_cents,
        status=status,
        notes=_optional_str(payload.get("notes")),
    )
    db.session.add(row)
    db.session.flush()

    line_items = payload.get("line_items") or ()
    for item in line_items:
        expense_journal_ulid = _require_str(
            "expense_journal_ulid",
            item.get("expense_journal_ulid"),
        )
        expense_journal = db.session.get(Journal, expense_journal_ulid)
        if expense_journal is None:
            raise LookupError(
                f"expense journal not found: {expense_journal_ulid}"
            )
        claimed_line = _require_int_ge(
            "claimed_amount_cents",
            item.get("claimed_amount_cents", 0),
            0,
        )
        approved_line = _require_int_ge(
            "approved_amount_cents",
            item.get("approved_amount_cents", 0),
            0,
        )
        received_line = _require_int_ge(
            "received_amount_cents",
            item.get("received_amount_cents", 0),
            0,
        )
        if approved_line > claimed_line:
            raise ValueError("line approved exceeds claimed")
        if received_line > approved_line:
            raise ValueError("line received exceeds approved")
        line_status = _optional_str(item.get("status")) or "included"
        if line_status not in REIMBURSEMENT_LINE_STATUSES:
            raise ValueError("invalid reimbursement line status")
        db.session.add(
            ReimbursementLine(
                claim_ulid=row.ulid,
                expense_journal_ulid=expense_journal_ulid,
                claimed_amount_cents=claimed_line,
                approved_amount_cents=approved_line,
                received_amount_cents=received_line,
                status=line_status,
                notes=_optional_str(item.get("notes")),
            )
        )

    db.session.flush()
    event_bus.emit(
        domain="finance",
        operation="reimbursement_claim_submitted",
        request_id=str(payload.get("request_id") or row.ulid),
        actor_ulid=payload.get("actor_ulid"),
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "grant_ulid": grant.ulid,
            "project_ulid": row.project_ulid,
            "funding_demand_ulid": row.funding_demand_ulid,
            "claim_number": row.claim_number,
        },
        changed={
            "fields": [
                "period_start",
                "period_end",
                "submitted_on",
                "claimed_amount_cents",
                "approved_amount_cents",
                "received_amount_cents",
                "status",
            ]
        },
        chain_key="finance.reimbursement",
    )
    return _reimbursement_view(row)


def mark_disbursed(payload: dict[str, Any]) -> dict[str, Any]:
    reimbursement_ulid = _optional_str(payload.get("reimbursement_ulid"))
    if not reimbursement_ulid:
        reimbursement_ulid = _optional_str(payload.get("reimbursement_id"))
    if not reimbursement_ulid:
        raise ValueError("reimbursement_ulid is required")

    row = db.session.get(Reimbursement, reimbursement_ulid)
    if row is None:
        raise LookupError(f"reimbursement not found: {reimbursement_ulid}")

    status = _optional_str(payload.get("status")) or "paid"
    if status not in {"paid", "void", "closed"}:
        raise ValueError("status must be paid, void, or closed")

    row.status = "void" if status == "void" else status
    if row.status == "paid":
        received_on = _optional_str(payload.get("received_on"))
        row.received_on = received_on or row.received_on or now_iso8601_ms()[:10]
        received_amount = payload.get("received_amount_cents")
        if received_amount is None:
            received_amount = row.approved_amount_cents or row.claimed_amount_cents
        row.received_amount_cents = _require_int_ge(
            "received_amount_cents", received_amount, 0
        )
        if row.approved_amount_cents == 0:
            row.approved_amount_cents = row.claimed_amount_cents
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="reimbursement_claim_updated",
        request_id=str(payload.get("request_id") or row.ulid),
        actor_ulid=payload.get("actor_ulid"),
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "grant_ulid": row.grant_ulid,
            "project_ulid": row.project_ulid,
            "funding_demand_ulid": row.funding_demand_ulid,
        },
        changed={
            "fields": [
                "status",
                "approved_amount_cents",
                "received_amount_cents",
                "received_on",
            ]
        },
        chain_key="finance.reimbursement",
    )
    return _reimbursement_view(row)


def record_disbursement(payload: dict[str, Any]) -> dict[str, Any]:
    expense_journal_ulid = _require_str(
        "expense_journal_ulid",
        payload.get("expense_journal_ulid"),
    )
    expense_journal = db.session.get(Journal, expense_journal_ulid)
    if expense_journal is None:
        raise LookupError(
            f"expense journal not found: {expense_journal_ulid}"
        )

    method = _optional_str(payload.get("method")) or "other"
    if method not in DISBURSEMENT_METHODS:
        raise ValueError("invalid disbursement method")

    status = _optional_str(payload.get("status")) or "recorded"
    if status not in DISBURSEMENT_STATUSES:
        raise ValueError("invalid disbursement status")

    row = Disbursement(
        expense_journal_ulid=expense_journal_ulid,
        grant_ulid=_optional_str(payload.get("grant_ulid"))
        or expense_journal.grant_ulid,
        project_ulid=_require_str(
            "project_ulid",
            payload.get("project_ulid") or expense_journal.project_ulid,
        ),
        funding_demand_ulid=_optional_str(
            payload.get("funding_demand_ulid")
            or expense_journal.funding_demand_ulid
        ),
        amount_cents=_require_int_ge(
            "amount_cents",
            payload.get("amount_cents"),
            0,
        ),
        disbursed_on=_date_required(
            "disbursed_on",
            payload.get("disbursed_on"),
        ),
        method=method,
        reference=_optional_str(payload.get("reference")),
        status=status,
        notes=_optional_str(payload.get("notes")),
    )
    db.session.add(row)
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="disbursement_recorded",
        request_id=str(payload.get("request_id") or row.ulid),
        actor_ulid=payload.get("actor_ulid"),
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "grant_ulid": row.grant_ulid,
            "project_ulid": row.project_ulid,
            "funding_demand_ulid": row.funding_demand_ulid,
            "expense_journal_ulid": row.expense_journal_ulid,
            "method": row.method,
            "amount_cents": row.amount_cents,
        },
        chain_key="finance.disbursement",
    )
    return _disbursement_view(row)


def prepare_grant_report(payload: dict[str, Any]) -> dict[str, Any]:
    grant_ulid = _optional_str(payload.get("grant_ulid"))
    if not grant_ulid:
        grant_ulid = _optional_str(payload.get("grant_id"))
    if not grant_ulid:
        raise ValueError("grant_ulid is required")

    period_start = _date_required("period_start", payload.get("period_start"))
    period_end = _date_required("period_end", payload.get("period_end"))

    grant = db.session.get(Grant, grant_ulid)
    if grant is None:
        raise LookupError(f"grant not found: {grant_ulid}")

    fund = _fund_by_code(grant.fund_code)

    reserve_rows = db.session.execute(
        select(Reserve).where(Reserve.grant_ulid == grant.ulid)
    ).scalars()
    reserve_cents = sum(
        int(row.amount_cents or 0)
        for row in reserve_rows
        if row.status == "active"
    )

    enc_rows = db.session.execute(
        select(Encumbrance).where(Encumbrance.grant_ulid == grant.ulid)
    ).scalars()
    encumbered_cents = 0
    relieved_cents = 0
    for row in enc_rows:
        if row.status == "void":
            continue
        amount = int(row.amount_cents or 0)
        relieved = int(row.relieved_cents or 0)
        relieved_cents += relieved
        encumbered_cents += max(amount - relieved, 0)

    income_cents = _journal_total_for_codes(
        grant_ulid=grant.ulid,
        period_start=period_start,
        period_end=period_end,
        prefixes=("4",),
        invert_sign=True,
    )
    expense_cents = _journal_total_for_codes(
        grant_ulid=grant.ulid,
        period_start=period_start,
        period_end=period_end,
        prefixes=("5", "6"),
    )

    disbursement_rows = db.session.execute(
        select(Disbursement).where(Disbursement.grant_ulid == grant.ulid)
    ).scalars()
    disbursed_cents = sum(
        int(row.amount_cents or 0)
        for row in disbursement_rows
        if row.status == "recorded"
        and period_start <= row.disbursed_on <= period_end
    )

    claim_rows = db.session.execute(
        select(Reimbursement).where(Reimbursement.grant_ulid == grant.ulid)
    ).scalars()
    claimed_cents = 0
    approved_cents = 0
    received_cents = 0
    claim_ulids: list[str] = []
    for row in claim_rows:
        if row.status == "void":
            continue
        claim_ulids.append(row.ulid)
        claimed_cents += int(row.claimed_amount_cents or 0)
        approved_cents += int(row.approved_amount_cents or 0)
        received_cents += int(row.received_amount_cents or 0)

    return {
        "grant": _grant_view(grant, fund=fund),
        "period": {
            "start_on": period_start,
            "end_on": period_end,
        },
        "funding": {
            "amount_awarded_cents": int(grant.amount_awarded_cents or 0),
            "income_received_cents": income_cents,
            "remaining_authority_cents": max(
                int(grant.amount_awarded_cents or 0) - expense_cents,
                0,
            ),
        },
        "commitments": {
            "reserved_cents": reserve_cents,
            "encumbered_open_cents": encumbered_cents,
            "encumbrance_relieved_cents": relieved_cents,
        },
        "spending": {
            "posted_expense_cents": expense_cents,
            "disbursed_cents": disbursed_cents,
        },
        "reimbursements": {
            "claimed_cents": claimed_cents,
            "approved_cents": approved_cents,
            "received_cents": received_cents,
            "outstanding_cents": max(approved_cents - received_cents, 0),
            "claim_ulids": sorted(claim_ulids),
        },
        "traceability": {
            "grant_ulid": grant.ulid,
            "fund_code": grant.fund_code,
            "fund_id": getattr(fund, "ulid", None),
            "project_ulid": grant.project_ulid,
            "income_journal_ulids": sorted(
                {
                    row.journal_ulid
                    for row, _journal in db.session.execute(
                        select(JournalLine, Journal)
                        .join(Journal, Journal.ulid == JournalLine.journal_ulid)
                        .where(JournalLine.grant_ulid == grant.ulid)
                        .where(Journal.happened_at_utc >= period_start)
                        .where(Journal.happened_at_utc <= f"{period_end}T23:59:59Z")
                    ).all()
                    if row.account_code.startswith(("4",))
                }
            ),
            "expense_journal_ulids": sorted(
                {
                    row.journal_ulid
                    for row, _journal in db.session.execute(
                        select(JournalLine, Journal)
                        .join(Journal, Journal.ulid == JournalLine.journal_ulid)
                        .where(JournalLine.grant_ulid == grant.ulid)
                        .where(Journal.happened_at_utc >= period_start)
                        .where(Journal.happened_at_utc <= f"{period_end}T23:59:59Z")
                    ).all()
                    if row.account_code.startswith(("5", "6"))
                }
            ),
            "reserve_ulids": sorted(
                row.ulid
                for row in db.session.execute(
                    select(Reserve).where(Reserve.grant_ulid == grant.ulid)
                ).scalars()
            ),
            "encumbrance_ulids": sorted(
                row.ulid
                for row in db.session.execute(
                    select(Encumbrance).where(Encumbrance.grant_ulid == grant.ulid)
                ).scalars()
                if row.status != "void"
            ),
            "disbursement_ulids": sorted(
                row.ulid
                for row in db.session.execute(
                    select(Disbursement).where(Disbursement.grant_ulid == grant.ulid)
                ).scalars()
                if row.status == "recorded"
            ),
        },
    }
