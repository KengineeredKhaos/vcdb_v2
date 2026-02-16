# app/extensions/contracts/entity_v2.py  (wizard section)

from dataclasses import dataclass
from typing import Any

from app.extensions.errors import ContractError
from app.slices.entity import guards as ent_guards
from app.slices.entity.mapper import WizardStepDTO
from app.slices.entity.services_wizard import (
    wizard_create_org_core as _wizard_create_org_core,
)
from app.slices.entity.services_wizard import (
    wizard_create_person_core as _wizard_create_person_core,
)


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


@dataclass(frozen=True, slots=True)
class EnsurePersonResultDTO:
    entity_ulid: str
    created: bool


@dataclass(frozen=True)
class WizardStepDTO:
    entity_ulid: str
    changed_fields: tuple[str, ...]
    as_of_iso: str


# -----------------
# Wizard Contracts
# -----------------


def wizard_create_person_core(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str | None = None,
    dob: str | None = None,
    last_4: str | None = None,
) -> WizardStepDTO:
    where = "entity_v2.wizard_create_person_core"
    try:
        return _wizard_create_person_core(
            first_name=first_name,
            last_name=last_name,
            preferred_name=preferred_name,
            dob=dob,
            last_4=last_4,
        )
    except ContractError:
        raise
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def wizard_create_org_core(
    *,
    legal_name: str,
    dba_name: str | None = None,
    ein: str | None = None,
) -> WizardStepDTO:
    where = "entity_v2.wizard_create_org_core"
    try:
        return _wizard_create_org_core(
            legal_name=legal_name,
            dba_name=dba_name,
            ein=ein,
        )
    except ContractError:
        raise
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc
