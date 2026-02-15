# app/extensions/contracts/entity_v2.py  (wizard section)

from dataclasses import dataclass
from typing import Any

from app.extensions.errors import ContractError
from app.slices.entity import guards as ent_guards
from app.slices.entity import mapper
from app.slices.entity.services_wizard import (
    cmd_wizard_create_person_core,
    cmd_wizard_set_address_primary,
    cmd_wizard_set_contact_primary,
    cmd_wizard_set_single_role,
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


@dataclass(frozen=True)
class WizardPersonCommitResultDTO:
    entity_ulid: str
    created: bool
    changed_fields: tuple[str, ...]
    as_of_iso: str


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
    ent, changed, as_of_iso = cmd_wizard_create_person_core(
        first_name=first_name,
        last_name=last_name,
        preferred_name=preferred_name,
        dob=dob,
        last_4=last_4,
    )
    return WizardStepDTO(
        entity_ulid=ent.ulid,
        changed_fields=changed,
        as_of_iso=as_of_iso,
    )


def wizard_commit_person(
    *,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> WizardPersonCommitResultDTO:
    where = "entity_v2.wizard_commit_person"
    try:
        from app.slices.entity import services_wizard as wiz

        res = wiz.cmd_wizard_person_commit(
            payload=payload,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return WizardPersonCommitResultDTO(
            entity_ulid=res.entity_ulid,
            created=res.created,
            changed_fields=res.changed_fields,
            as_of_iso=res.as_of_iso,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Legacy Contracts
# -----------------


def ensure_person(
    *,
    first_name: str,
    last_name: str,
    email: str | None = None,
    phone: str | None = None,
    request_id: str,
    actor_ulid: str | None,
) -> EnsurePersonResultDTO:
    where = "entity_v2.ensure_person"
    try:
        from app.slices.entity import services as entity_svc

        res = entity_svc.cmd_person_ensure_by_contact(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return EnsurePersonResultDTO(
            entity_ulid=res.entity_ulid,
            created=res.created,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc
