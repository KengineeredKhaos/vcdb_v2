# app/extensions/contracts/entity_v2.py  (wizard section)

from dataclasses import dataclass
from typing import Any

from app.extensions.errors import ContractError


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc
    msg = str(exc) or exc.__class__.__name__
    if isinstance(exc, ValueError):
        return ContractError("bad_argument", where, msg, 400)
    if isinstance(exc, PermissionError):
        return ContractError("permission_denied", where, msg, 403)
    if isinstance(exc, LookupError):
        return ContractError("not_found", where, msg, 404)
    return ContractError(
        "internal_error",
        where,
        "unexpected error in contract; see logs",
        500,
        data={"exc_type": exc.__class__.__name__},
    )


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


# -----------------
# Wizard Contracts
# -----------------


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
