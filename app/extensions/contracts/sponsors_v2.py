# app/extensions/contracts/sponsors_v2.py

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Final

from app.extensions.errors import ContractError
from app.slices.sponsors import mapper as sp_mapper
from app.slices.sponsors import services as sp_svc
from app.slices.sponsors import services_funding_realization as sp_realize

from ._funding_dto import FundingIntentTotalsDTO, MoneyByKeyDTO, MoneyLinksDTO

_SCHEMA: Final[str] = "contract:sponsors_v2"


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
class FundingRealizationRequestDTO:
    intent_ulid: str
    amount_cents: int
    happened_at_utc: str
    fund_key: str
    receipt_method: str

    income_kind: str | None = None
    reserve_on_receive: bool | None = None
    memo: str | None = None
    actor_ulid: str | None = None
    actor_rbac_roles: tuple[str, ...] = ()
    actor_domain_roles: tuple[str, ...] = ()
    request_id: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FundingRealizationDTO:
    intent_ulid: str
    sponsor_entity_ulid: str
    funding_demand_ulid: str
    project_ulid: str | None

    amount_cents: int
    fund_key: str

    journal_ulid: str
    reserve_ulid: str | None

    status: str
    decision_fingerprint: str
    flags: tuple[str, ...] = ()

# -----------------
# New Paradigm
# -----------------


def _load_provider(where: str):
    """
    Sponsors slice must provide a read-only function with this signature:

        get_funding_intent_totals(funding_demand_ulid: str) -> dict[str, Any]

    Expected keys:
      funding_demand_ulid
      pledged_cents
      pledged_by_sponsor: list[{"key": sponsor_ulid, "amount_cents": int}, ...]
      pledge_ulids: list[str]
      donation_ulids: list[str]  (optional)
    """
    try:
        mod = importlib.import_module("app.slices.sponsors.services_funding")
        fn = mod.get_funding_intent_totals
        return fn
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            code="provider_missing",
            where=where,
            message=(
                "Sponsors provider missing: "
                "app.slices.sponsors.services_funding.get_funding_intent_totals"
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


def get_funding_intent_totals(
    funding_demand_ulid: str,
) -> FundingIntentTotalsDTO:
    where = "sponsors_v2.get_funding_intent_totals"
    try:
        provider = _load_provider(where)
        raw = provider(funding_demand_ulid)

        pledge_ulids = tuple(raw.get("pledge_ulids") or ())
        donation_ulids = tuple(raw.get("donation_ulids") or ())

        links = MoneyLinksDTO(
            pledge_ulids=pledge_ulids,
            donation_ulids=donation_ulids,
        )

        return FundingIntentTotalsDTO(
            funding_demand_ulid=str(raw["funding_demand_ulid"]),
            pledged_cents=int(raw.get("pledged_cents") or 0),
            pledged_by_sponsor=_to_money_by_key(
                raw.get("pledged_by_sponsor")
            ),
            links=links,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc



def realize_funding_intent(
    req: FundingRealizationRequestDTO,
) -> FundingRealizationDTO:
    where = "sponsors_v2.realize_funding_intent"
    try:
        out = sp_realize.realize_funding_intent(
            intent_ulid=req.intent_ulid,
            amount_cents=req.amount_cents,
            happened_at_utc=req.happened_at_utc,
            fund_key=req.fund_key,
            income_kind=req.income_kind,
            receipt_method=req.receipt_method,
            reserve_on_receive=req.reserve_on_receive,
            memo=req.memo,
            actor_ulid=req.actor_ulid,
            actor_rbac_roles=req.actor_rbac_roles,
            actor_domain_roles=req.actor_domain_roles,
            request_id=req.request_id,
            dry_run=req.dry_run,
        )
        return FundingRealizationDTO(
            intent_ulid=out.intent_ulid,
            sponsor_entity_ulid=out.sponsor_entity_ulid,
            funding_demand_ulid=out.funding_demand_ulid,
            project_ulid=out.project_ulid,
            amount_cents=out.amount_cents,
            fund_key=out.fund_key,
            journal_ulid=out.journal_ulid,
            reserve_ulid=out.reserve_ulid,
            status=out.status,
            decision_fingerprint=out.decision_fingerprint,
            flags=out.flags,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Old Paradigm
# below this line
# -----------------


def ensure_sponsor(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    where = "sponsors_v2.ensure_sponsor"
    try:
        return sp_svc.ensure_sponsor(
            sponsor_entity_ulid=entity_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_sponsor_view(*, entity_ulid: str) -> dict[str, Any] | None:
    where = "sponsors_v2.get_sponsor_view"
    try:
        view = sp_svc.sponsor_view(entity_ulid)
        return None if view is None else sp_mapper.sponsor_view_to_dto(view)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def upsert_capabilities(
    *,
    entity_ulid: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    where = "sponsors_v2.upsert_capabilities"
    try:
        hist_ulid = sp_svc.upsert_capabilities(
            sponsor_entity_ulid=entity_ulid,
            payload=payload,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        view = sp_svc.sponsor_view(entity_ulid)
        return {
            "changed": hist_ulid is not None,
            "history_ulid": hist_ulid,
            "view": None
            if view is None
            else sp_mapper.sponsor_view_to_dto(view),
        }
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc
