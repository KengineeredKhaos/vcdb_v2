# app/extensions/contracts/auth/v1.py
from dataclasses import dataclass


@dataclass(frozen=True)
class RBACRoleDTO:
    name: str
    description: str
    is_active: bool


@dataclass(frozen=True)
class AccountRolesDTO:
    account_ulid: str
    roles: list[str]


# Facade
def list_rbac_roles() -> list[RBACRoleDTO]:
    from app.slices.auth import services as svc

    return [
        RBACRoleDTO(r.name, r.description, r.is_active)
        for r in svc.list_rbac_roles()
    ]


def get_account_roles(account_ulid: str) -> AccountRolesDTO:
    from app.slices.auth import services as svc

    return AccountRolesDTO(
        account_ulid=account_ulid, roles=svc.get_account_roles(account_ulid)
    )


def set_account_roles(
    account_ulid: str, roles: list[str], actor_entity_ulid: str | None = None
) -> AccountRolesDTO:
    from app.slices.auth import services as svc

    svc.set_account_roles(
        account_ulid=account_ulid,
        roles=roles,
        actor_entity_ulid=actor_entity_ulid,
    )
    return get_account_roles(account_ulid)
