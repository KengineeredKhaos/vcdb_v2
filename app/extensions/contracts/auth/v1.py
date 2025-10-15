# app/extensions/contracts/auth/v1.py
from dataclasses import dataclass


@dataclass(frozen=True)
class RBACRoleDTO:
    code: str
    description: str | None
    is_active: bool


@dataclass(frozen=True)
class AccountRolesDTO:
    account_ulid: str
    roles: list[str]


def list_rbac_roles() -> list[RBACRoleDTO]:
    from app.slices.auth.services import list_roles

    rows = list_roles()
    return [
        RBACRoleDTO(
            code=r["code"],
            description=r["description"],
            is_active=r["is_active"],
        )
        for r in rows
    ]


def get_account_roles(account_ulid: str) -> AccountRolesDTO:
    from app.slices.auth.services import user_view

    try:
        view = user_view(account_ulid)
    except Exception:
        view = {"roles": []}
    return AccountRolesDTO(
        account_ulid=account_ulid, roles=list(view.get("roles") or [])
    )


def set_account_roles(
    account_ulid: str, roles: list[str], actor_entity_ulid: str | None = None
) -> AccountRolesDTO:
    from app.slices.auth.services import set_account_roles as svc_set

    svc_set(
        account_ulid=account_ulid,
        roles=roles,
        actor_entity_ulid=actor_entity_ulid,
    )
    return get_account_roles(account_ulid)
