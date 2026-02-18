# app/extensions/contracts/entity_v2.py

from __future__ import annotations

from app.extensions.errors import ContractError
from app.slices.entity import guards as ent_guards
from app.slices.entity import services as ent_services
from app.slices.entity.mapper import OrgView, PersonView, WizardSummaryDTO

# -----------------
# Contract Error
# Handlers
# -----------------


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


# -----------------
# Guards and Fills
# -----------------


def require_person_entity_ulid(
    entity_ulid: str | None,
    *,
    allow_archived: bool = False,
) -> str:
    where = "entity_v2.require_person_entity_ulid"
    try:
        return ent_guards.require_person_entity_ulid(
            entity_ulid,
            kind,
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


# -----------------
# Summary Views
# -----------------


def get_wizard_summary(entity_ulid: str) -> WizardSummaryDTO:
    where = "entity_v2.get_wizard_summary"
    try:
        return ent_services.get_wizard_summary(entity_ulid=entity_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_person_view(entity_ulid: str) -> PersonView:
    where = "entity_v2.get_person_view"
    try:
        # Guard: must be a person entity.
        ent_guards.require_person_entity_ulid(entity_ulid)
        return ent_services.get_person_view(entity_ulid=entity_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_org_view(entity_ulid: str) -> OrgView:
    where = "entity_v2.get_org_view"
    try:
        # Guard: must be an org entity.
        ent_guards.require_org_entity_ulid(entity_ulid)
        return ent_services.get_org_view(entity_ulid=entity_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc
