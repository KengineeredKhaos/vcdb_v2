from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.extensions.errors import ContractError
from app.slices.auth import services as auth_services
from app.slices.auth import services_policy_rbac as policy_svc


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
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found",
            where=where,
            message=str(exc),
            http_status=404,
        )
    return ContractError(
        code="internal_error",
        where=where,
        message=f"unexpected: {exc.__class__.__name__}",
        http_status=500,
    )


def list_rbac_role_choices() -> list[tuple[str, str]]:
    where = "auth_v1.list_rbac_role_choices"
    try:
        return policy_svc.list_rbac_role_choices()
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_rbac_role_view(role_code: str):
    where = "auth_v1.get_rbac_role_view"
    try:
        return policy_svc.get_rbac_role_view(role_code)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def validate_rbac_role_code(role_code: str) -> str:
    where = "auth_v1.validate_rbac_role_code"
    try:
        return policy_svc.validate_rbac_role_code(role_code)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def create_account(
    *,
    username: str,
    password: str,
    roles: Iterable[str] | None = None,
    email: str | None = None,
    entity_ulid: str | None = None,
    is_active: bool = True,
    must_change_password: bool = True,
) -> dict[str, Any]:
    where = "auth_v1.create_account"
    try:
        return auth_services.create_account(
            username=username,
            password=password,
            roles=roles,
            email=email,
            entity_ulid=entity_ulid,
            is_active=is_active,
            must_change_password=must_change_password,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def set_account_roles(
    account_ulid: str,
    roles: Iterable[str] | None,
) -> dict[str, Any]:
    where = "auth_v1.set_account_roles"
    try:
        return auth_services.set_account_roles(account_ulid, roles)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_user_view(account_ulid: str) -> dict[str, Any]:
    where = "auth_v1.get_user_view"
    try:
        return auth_services.get_user_view(account_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_user_views() -> list[dict[str, Any]]:
    where = "auth_v1.list_user_views"
    try:
        return auth_services.list_user_views()
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def admin_reset_password(
    account_ulid: str,
    temporary_password: str,
) -> dict[str, Any]:
    where = "auth_v1.admin_reset_password"
    try:
        return auth_services.admin_reset_password(
            account_ulid=account_ulid,
            temporary_password=temporary_password,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def unlock_account(account_ulid: str) -> dict[str, Any]:
    where = "auth_v1.unlock_account"
    try:
        return auth_services.unlock_account(account_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def set_account_active(
    account_ulid: str,
    *,
    is_active: bool,
) -> dict[str, Any]:
    where = "auth_v1.set_account_active"
    try:
        return auth_services.set_account_active(
            account_ulid,
            is_active=is_active,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc
