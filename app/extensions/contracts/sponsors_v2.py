# app/extensions/contracts/sponsors_v2.py

from __future__ import annotations

from typing import Any, Final

from app.extensions.errors import ContractError
from app.slices.sponsors import mapper as sp_mapper
from app.slices.sponsors import services as sp_svc

_SCHEMA: Final[str] = "contract:sponsors_v2"


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc
    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=str(exc),
            http_status=400,
        )
    return ContractError(
        code="internal_error",
        where=where,
        message=str(exc),
        http_status=500,
    )


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
