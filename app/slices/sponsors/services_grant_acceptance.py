from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.extensions.contracts import finance_v2


@dataclass(frozen=True)
class GrantAcceptanceDTO:
    sponsor_ulid: str
    is_grant_award: bool
    acceptance_status: str
    accepted_on: date
    award_name: str
    amount_offered_cents: int
    award_number: str | None = None
    offer_reference: str | None = None
    purpose_summary: str | None = None
    conditions_summary: str | None = None
    source_document_ref: str | None = None
    sponsor_contact_ref: str | None = None
    award_start_on: date | None = None
    award_end_on: date | None = None
    project_ulid: str | None = None
    notes: str | None = None
    fund_code: str | None = None
    restriction_type: str | None = None
    funding_mode: str | None = None
    reporting_frequency: str | None = None
    allowable_expense_kinds_csv: str | None = None
    match_required_cents: int = 0
    program_income_allowed: bool = False


@dataclass(frozen=True)
class CreateGrantPayload:
    sponsor_ulid: str
    award_name: str
    amount_awarded_cents: int
    fund_code: str
    restriction_type: str
    funding_mode: str
    reporting_frequency: str
    award_number: str | None = None
    start_on: str | None = None
    end_on: str | None = None
    project_ulid: str | None = None
    allowable_expense_kinds: tuple[str, ...] = ()
    match_required_cents: int = 0
    program_income_allowed: bool = False
    conditions_summary: str | None = None
    source_document_ref: str | None = None
    notes: str | None = None


def _csv_to_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for raw in value.split(","):
        key = str(raw or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return tuple(sorted(out))


def _date_range(dto: GrantAcceptanceDTO) -> tuple[str, str]:
    start = dto.award_start_on or dto.accepted_on
    end = dto.award_end_on or dto.award_start_on or dto.accepted_on
    if end < start:
        raise ValueError("award_end_on cannot be before award_start_on")
    return (start.isoformat(), end.isoformat())


def to_create_grant_payload(dto: GrantAcceptanceDTO) -> CreateGrantPayload:
    if not dto.is_grant_award:
        raise ValueError("acceptance does not create a grant")

    if not dto.fund_code:
        raise ValueError("fund_code is required for grant awards")
    if not dto.restriction_type:
        raise ValueError(
            "restriction_type is required for grant awards"
        )
    if not dto.funding_mode:
        raise ValueError("funding_mode is required for grant awards")
    if not dto.reporting_frequency:
        raise ValueError(
            "reporting_frequency is required for grant awards"
        )

    start_on, end_on = _date_range(dto)
    return CreateGrantPayload(
        sponsor_ulid=dto.sponsor_ulid,
        award_name=dto.award_name,
        amount_awarded_cents=int(dto.amount_offered_cents or 0),
        fund_code=str(dto.fund_code).strip(),
        restriction_type=str(dto.restriction_type).strip(),
        funding_mode=str(dto.funding_mode).strip(),
        reporting_frequency=str(dto.reporting_frequency).strip(),
        award_number=dto.award_number,
        start_on=start_on,
        end_on=end_on,
        project_ulid=dto.project_ulid,
        allowable_expense_kinds=_csv_to_tuple(
            dto.allowable_expense_kinds_csv
        ),
        match_required_cents=int(dto.match_required_cents or 0),
        program_income_allowed=bool(dto.program_income_allowed),
        conditions_summary=dto.conditions_summary,
        source_document_ref=dto.source_document_ref,
        notes=dto.notes,
    )


def create_finance_grant(
    dto: GrantAcceptanceDTO,
    *,
    actor_ulid: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    payload = to_create_grant_payload(dto)
    return finance_v2.create_grant_award(
        {
            "sponsor_ulid": payload.sponsor_ulid,
            "award_name": payload.award_name,
            "award_number": payload.award_number,
            "amount_awarded_cents": payload.amount_awarded_cents,
            "fund_code": payload.fund_code,
            "restriction_type": payload.restriction_type,
            "funding_mode": payload.funding_mode,
            "reporting_frequency": payload.reporting_frequency,
            "start_on": payload.start_on,
            "end_on": payload.end_on,
            "project_ulid": payload.project_ulid,
            "allowable_expense_kinds": list(
                payload.allowable_expense_kinds
            ),
            "match_required_cents": payload.match_required_cents,
            "program_income_allowed": payload.program_income_allowed,
            "conditions_summary": payload.conditions_summary,
            "source_document_ref": payload.source_document_ref,
            "notes": payload.notes,
            "status": "active",
            "actor_ulid": actor_ulid,
            "request_id": request_id,
        }
    )
