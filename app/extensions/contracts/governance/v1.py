# app/extension/contracts/governance/v1.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateDTO:
    code: str
    name: str


@dataclass(frozen=True)
class ServiceClassDTO:
    code: str
    label: str
    sort: int


@dataclass(frozen=True)
class DomainRoleDTO:
    code: str
    description: str


def get_states() -> list[StateDTO]:
    from app.slices.governance.services import list_states

    return [StateDTO(**x) for x in list_states()]


def get_service_classifications() -> list[ServiceClassDTO]:
    from app.slices.governance.services import list_service_classifications

    return [ServiceClassDTO(**x) for x in list_service_classifications()]


def get_domain_roles() -> list[DomainRolesDTO]:
    from app.slices.governance.services import list_domain_roles

    return [DomainRoleDTO(**x) for x in list_domain_roles()]
