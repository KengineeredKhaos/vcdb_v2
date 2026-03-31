from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.extensions.contracts import auth_v1, entity_v2
from app.extensions.errors import ContractError


@dataclass(frozen=True, slots=True)
class OperatorOnboardReviewDTO:
    first_name: str
    last_name: str
    preferred_name: str | None
    username: str
    email: str | None
    temporary_password: str
    role_code: str
    role_label: str
    role_summary: str
    display_name: str


@dataclass(frozen=True, slots=True)
class OperatorOnboardResultDTO:
    entity_ulid: str
    account_ulid: str
    username: str
    role_code: str
    display_name: str
    email: str | None
    role_label: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorRbacMaintenancePageDTO:
    title: str
    summary: str
    account_ulid: str
    entity_ulid: str | None
    username: str
    email: str | None
    display_name: str
    current_role_code: str | None
    current_role_label: str | None


@dataclass(frozen=True, slots=True)
class OperatorRbacMaintenanceResultDTO:
    account_ulid: str
    username: str
    role_code: str
    role_label: str
    display_name: str


def _clean_required(label: str, value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{label} is required.")
    return clean


def _clean_optional(value: str | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _display_name(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str | None,
) -> str:
    given = preferred_name or first_name
    return f"{given} {last_name}".strip()


def _resolve_role(role_code: str):
    try:
        clean_role = auth_v1.validate_rbac_role_code(role_code)
        return auth_v1.get_rbac_role_view(clean_role)
    except ContractError as exc:
        if exc.code == "bad_argument":
            raise ValueError(str(exc)) from exc
        raise


def build_operator_onboard_review(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str,
    username: str,
    email: str | None,
    temporary_password: str,
    role_code: str,
) -> OperatorOnboardReviewDTO:
    clean_first = str(first_name or "").strip()
    clean_last = str(last_name or "").strip()
    clean_preferred = str(preferred_name or "").strip() or None
    clean_username = str(username or "").strip()
    clean_email = str(email or "").strip().lower() or None
    clean_password = str(temporary_password or "")

    try:
        clean_role = auth_v1.validate_rbac_role_code(role_code)
        role_view = auth_v1.get_rbac_role_view(clean_role)
    except ContractError as exc:
        raise ValueError(str(exc)) from exc

    if not clean_first:
        raise ValueError("First name is required.")
    if not clean_last:
        raise ValueError("Last name is required.")
    if not clean_username:
        raise ValueError("Username is required.")
    if not clean_password:
        raise ValueError("Temporary password is required.")

    display_name = f"{clean_preferred or clean_first} {clean_last}".strip()

    return OperatorOnboardReviewDTO(
        first_name=clean_first,
        last_name=clean_last,
        preferred_name=clean_preferred,
        username=clean_username,
        email=clean_email,
        temporary_password=clean_password,
        role_code=role_view.code,
        role_label=role_view.label,
        role_summary=role_view.summary,
        display_name=display_name,
    )


def rehydrate_operator_onboard_review(
    payload: dict[str, Any],
) -> OperatorOnboardReviewDTO:
    return OperatorOnboardReviewDTO(
        first_name=str(payload.get("first_name") or ""),
        last_name=str(payload.get("last_name") or ""),
        preferred_name=(
            str(payload.get("preferred_name"))
            if payload.get("preferred_name")
            else None
        ),
        username=str(payload.get("username") or ""),
        email=(str(payload.get("email")) if payload.get("email") else None),
        temporary_password=str(payload.get("temporary_password") or ""),
        role_code=str(payload.get("role_code") or ""),
        role_label=str(payload.get("role_label") or ""),
        role_summary=str(payload.get("role_summary") or ""),
        display_name=str(payload.get("display_name") or ""),
    )


def review_payload_dict(
    review: OperatorOnboardReviewDTO,
) -> dict[str, str | None]:
    return {
        "first_name": review.first_name,
        "last_name": review.last_name,
        "preferred_name": review.preferred_name,
        "username": review.username,
        "email": review.email,
        "temporary_password": review.temporary_password,
        "role_code": review.role_code,
        "role_label": review.role_label,
        "role_summary": review.role_summary,
        "display_name": review.display_name,
    }


def commit_operator_onboard(
    *,
    actor_ulid: str,
    request_id: str | None = None,
    first_name: str,
    last_name: str,
    preferred_name: str,
    username: str,
    email: str | None,
    temporary_password: str,
    role_code: str,
) -> OperatorOnboardResultDTO:
    review = build_operator_onboard_review(
        first_name=first_name,
        last_name=last_name,
        preferred_name=preferred_name,
        username=username,
        email=email,
        temporary_password=temporary_password,
        role_code=role_code,
    )

    person = entity_v2.create_operator_core(
        first_name=review.first_name,
        last_name=review.last_name,
        preferred_name=review.preferred_name or "",
        actor_ulid=actor_ulid,
        request_id=request_id,
    )

    account = auth_v1.create_account(
        username=review.username,
        password=review.temporary_password,
        email=review.email,
        entity_ulid=person.entity_ulid,
        roles=[review.role_code],
        is_active=True,
        must_change_password=True,
    )

    return OperatorOnboardResultDTO(
        entity_ulid=person.entity_ulid,
        account_ulid=str(account["ulid"]),
        username=str(account["username"]),
        role_code=review.role_code,
        role_label=review.role_label,
        display_name=person.display_name,
        email=(str(account.get("email")) if account.get("email") else None),
    )


def build_rbac_maintenance_page(
    *,
    account_ulid: str,
) -> OperatorRbacMaintenancePageDTO:
    view = auth_v1.get_user_view(account_ulid)
    entity_ulid = view.get("entity_ulid") or None
    display_name = str(view.get("username") or "")

    if entity_ulid:
        label = entity_v2.get_entity_label(str(entity_ulid))
        display_name = label.display_name

    roles = tuple(view.get("roles") or ())
    current_role = str(roles[0]) if roles else None
    current_role_label = None
    if current_role:
        current_role_label = _resolve_role(current_role).label

    return OperatorRbacMaintenancePageDTO(
        title="Operator RBAC Maintenance",
        summary=(
            "Adjust the operator RBAC access level. Domain roles "
            "remain outside this workflow."
        ),
        account_ulid=str(view["ulid"]),
        entity_ulid=(str(entity_ulid) if entity_ulid else None),
        username=str(view["username"]),
        email=(str(view["email"]) if view.get("email") else None),
        display_name=display_name,
        current_role_code=current_role,
        current_role_label=current_role_label,
    )


def edit_operator_rbac_role(
    *,
    account_ulid: str,
    role_code: str,
) -> OperatorRbacMaintenanceResultDTO:
    role_view = _resolve_role(role_code)
    view = auth_v1.set_account_roles(account_ulid, [role_view.code])

    entity_ulid = view.get("entity_ulid") or None
    display_name = str(view.get("username") or "")
    if entity_ulid:
        label = entity_v2.get_entity_label(str(entity_ulid))
        display_name = label.display_name

    return OperatorRbacMaintenanceResultDTO(
        account_ulid=str(view["ulid"]),
        username=str(view["username"]),
        role_code=role_view.code,
        role_label=role_view.label,
        display_name=display_name,
    )
