# app/extensions/contracts/entity_v2.py

from __future__ import annotations

from app.extensions.errors import ContractError
from app.slices.entity import guards as ent_guards


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc
    msg = str(exc) or exc.__class__.__name__
    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=str(exc),
            http_status=400,
        )
    if isinstance(exc, PermissionError):
        return ContractError("permission_denied", where, msg, 403)
    if isinstance(exc, LookupError):
        return ContractError("not_found", where, msg, 404)
    return ContractError(
        code="internal_error",
        where=where,
        message=f"unexpected: {exc.__class__.__name__}",
        http_status=500,
    )


def require_person_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> str:
    where = "entity_v2.require_person_entity_ulid"
    try:
        return ent_guards.require_person_entity_ulid(
            entity_ulid,
            allow_archived=allow_archived,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def require_org_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> str:
    where = "entity_v2.require_org_entity_ulid"
    try:
        return ent_guards.require_org_entity_ulid(
            entity_ulid,
            allow_archived=allow_archived,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# DTO's
# -----------------

# See Entity Mapper for DTO's


# -----------------
# Entity Data
# Edit/Update
# -----------------
