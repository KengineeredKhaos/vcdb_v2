# app/slices/auth/services.py
"""
VCDB v2 — Auth slice services

Auth service deviation note
===========================

For the Auth slice, Ledger audit writes are intentionally route-owned.
These services perform business mutation and may call ``db.session.flush()``,
but they do NOT emit Ledger events and they do NOT commit transactions.

Auth routes own ``event_bus.emit(...)`` plus explicit commit / rollback
framing so login failure, logout success, and related session flows stay
simple and easy to audit.
"""

from __future__ import annotations

from collections.abc import Iterable

from flask import current_app
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.lib.chrono import utcnow_aware
from app.slices.auth.models import Role, User


def _utc_now_iso() -> str:
    return utcnow_aware().replace(microsecond=0).isoformat()


def _norm_code(code: str) -> str:
    return str(code or "").strip().lower()


def _norm_codes(codes: Iterable[str] | None) -> list[str]:
    if codes is None:
        return []
    if isinstance(codes, str):
        raise ValueError("Role codes must be a list, tuple, or set.")
    return sorted({_norm_code(code) for code in codes if str(code).strip()})


def _clean_username(username: str) -> str:
    value = str(username or "").strip()
    if not value:
        raise ValueError("Username is required.")
    return value


def _clean_email(email: str | None) -> str | None:
    value = str(email or "").strip().lower()
    return value or None


def _require_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return value


def _get_user_or_raise(user_ulid: str) -> User:
    user = db.session.get(User, user_ulid)
    if not user:
        raise LookupError("User not found.")
    return user


def _role_codes_for_user(user: User) -> list[str]:
    return sorted(
        {
            _norm_code(role.code)
            for role in (user.roles or [])
            if role.is_active and role.code
        }
    )


def _active_role_map() -> dict[str, Role]:
    rows = db.session.execute(
        select(Role).where(Role.is_active.is_(True))
    ).scalars()
    return {_norm_code(row.code): row for row in rows if row.code}


def _find_user_by_username(username: str) -> User | None:
    value = str(username or "").strip().lower()
    if not value:
        return None

    return (
        db.session.execute(
            select(User).where(
                func.lower(User.username) == value,
            )
        )
        .unique()
        .scalar_one_or_none()
    )


def _user_view_dict(user: User) -> dict[str, object]:
    return {
        "ulid": user.ulid,
        "entity_ulid": user.entity_ulid,
        "username": user.username,
        "email": user.email or "",
        "is_active": bool(user.is_active),
        "is_locked": bool(user.is_locked),
        "must_change_password": bool(user.must_change_password),
        "failed_login_attempts": int(user.failed_login_attempts or 0),
        "locked_at_utc": user.locked_at_utc,
        "locked_by_ulid": user.locked_by_ulid,
        "last_login_at_utc": user.last_login_at_utc,
        "password_changed_at_utc": user.password_changed_at_utc,
        "reset_issued_at_utc": user.reset_issued_at_utc,
        "roles": _role_codes_for_user(user),
    }


def user_view(user_ulid: str) -> dict[str, object]:
    user = _get_user_or_raise(user_ulid)
    return _user_view_dict(user)


def get_user_view(account_ulid: str) -> dict[str, object]:
    return user_view(account_ulid)


def get_auth_failure_view(username: str) -> dict[str, object] | None:
    user = _find_user_by_username(username)
    if user is None:
        return None
    return _user_view_dict(user)


def list_user_views() -> list[dict[str, object]]:
    rows = (
        db.session.execute(
            select(User).order_by(func.lower(User.username), User.ulid)
        )
        .unique()
        .scalars()
        .all()
    )
    return [_user_view_dict(row) for row in rows]


def any_admin_account_exists() -> bool:
    admin_ulid = db.session.execute(
        select(User.ulid)
        .join(User.roles)
        .where(func.lower(Role.code) == "admin")
        .limit(1)
    ).scalar_one_or_none()
    return admin_ulid is not None


def get_user_roles(user_ulid: str) -> list[str]:
    user = db.session.get(User, user_ulid)
    if not user:
        return []
    return _role_codes_for_user(user)


def list_all_role_codes() -> list[str]:
    return sorted(_active_role_map().keys())


def create_account(
    *,
    username: str,
    password: str,
    roles: Iterable[str] | None = None,
    email: str | None = None,
    entity_ulid: str | None = None,
    is_active: bool = True,
    must_change_password: bool = True,
) -> dict[str, object]:
    clean_username = _clean_username(username)
    clean_email = _clean_email(email)
    clean_password = _require_password(password)

    existing_username = db.session.execute(
        select(User).where(
            func.lower(User.username) == clean_username.lower()
        )
    ).scalar_one_or_none()
    if existing_username:
        raise ValueError("Username already exists.")

    if clean_email:
        existing_email = db.session.execute(
            select(User).where(func.lower(User.email) == clean_email)
        ).scalar_one_or_none()
        if existing_email:
            raise ValueError("Email already exists.")

    user = User(
        entity_ulid=entity_ulid,
        username=clean_username,
        email=clean_email,
        password_hash=generate_password_hash(clean_password),
        is_active=bool(is_active),
        is_locked=False,
        must_change_password=bool(must_change_password),
        failed_login_attempts=0,
        password_changed_at_utc=_utc_now_iso(),
    )
    db.session.add(user)
    db.session.flush()

    set_account_roles(user.ulid, roles or ["user"])
    return user_view(user.ulid)


def bootstrap_first_admin(
    *,
    username: str,
    password: str,
    email: str | None = None,
    entity_ulid: str | None = None,
) -> dict[str, object]:
    if any_admin_account_exists():
        raise PermissionError("First-admin bootstrap is closed.")

    return create_account(
        username=username,
        password=password,
        roles=["admin"],
        email=email,
        entity_ulid=entity_ulid,
        is_active=True,
        must_change_password=False,
    )


def set_account_roles(
    account_ulid: str,
    roles: Iterable[str] | None,
) -> dict[str, object]:
    user = _get_user_or_raise(account_ulid)
    wanted_codes = _norm_codes(roles)
    role_map = _active_role_map()

    unknown = sorted(code for code in wanted_codes if code not in role_map)
    if unknown:
        raise ValueError(
            "Unknown or inactive role codes: " + ", ".join(unknown)
        )

    user.roles = [role_map[code] for code in wanted_codes]
    db.session.flush()
    return user_view(user.ulid)


def set_password(
    account_ulid: str,
    new_password: str,
    *,
    must_change_password: bool = False,
    unlock: bool = False,
) -> dict[str, object]:
    user = _get_user_or_raise(account_ulid)
    clean_password = _require_password(new_password)
    now_iso = _utc_now_iso()

    user.password_hash = generate_password_hash(clean_password)
    user.password_changed_at_utc = now_iso
    user.must_change_password = bool(must_change_password)
    user.failed_login_attempts = 0

    if unlock:
        user.is_locked = False
        user.locked_at_utc = None
        user.locked_by_ulid = None

    db.session.flush()
    return user_view(user.ulid)


def admin_reset_password(
    account_ulid: str,
    temporary_password: str,
) -> dict[str, object]:
    user = _get_user_or_raise(account_ulid)
    view = set_password(
        account_ulid,
        temporary_password,
        must_change_password=True,
        unlock=False,
    )
    user.reset_issued_at_utc = _utc_now_iso()
    db.session.flush()
    return user_view(user.ulid)


def set_account_active(
    account_ulid: str,
    *,
    is_active: bool,
) -> dict[str, object]:
    user = _get_user_or_raise(account_ulid)
    user.is_active = bool(is_active)
    db.session.flush()
    return user_view(user.ulid)


def lock_account(
    account_ulid: str,
    *,
    locked_by_ulid: str | None = None,
) -> dict[str, object]:
    user = _get_user_or_raise(account_ulid)
    user.is_locked = True
    user.locked_at_utc = _utc_now_iso()
    user.locked_by_ulid = locked_by_ulid
    db.session.flush()
    return user_view(user.ulid)


def unlock_account(
    account_ulid: str,
) -> dict[str, object]:
    user = _get_user_or_raise(account_ulid)
    user.is_locked = False
    user.failed_login_attempts = 0
    user.locked_at_utc = None
    user.locked_by_ulid = None
    db.session.flush()
    return user_view(user.ulid)


def change_own_password(
    account_ulid: str,
    *,
    current_password: str,
    new_password: str,
) -> dict[str, object]:
    user = _get_user_or_raise(account_ulid)

    if user.is_locked:
        raise ValueError("Account is locked.")

    if not check_password_hash(
        user.password_hash, str(current_password or "")
    ):
        raise ValueError("Current password is incorrect.")

    clean_password = _require_password(new_password)
    user.password_hash = generate_password_hash(clean_password)
    user.password_changed_at_utc = _utc_now_iso()
    user.must_change_password = False
    user.failed_login_attempts = 0
    db.session.flush()
    return user_view(user.ulid)


def authenticate(username: str, password: str) -> dict[str, object]:
    user = _find_user_by_username(username)
    if not user:
        raise ValueError("Invalid username or password.")

    if not user.is_active:
        raise ValueError("Invalid username or password.")

    if user.is_locked:
        raise ValueError("Invalid username or password.")

    if not check_password_hash(user.password_hash, str(password or "")):
        max_attempts = int(
            current_app.config.get("AUTH_MAX_FAILED_ATTEMPTS", 5)
        )
        user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= max_attempts:
            user.is_locked = True
            user.locked_at_utc = _utc_now_iso()
            user.locked_by_ulid = None
        db.session.flush()
        raise ValueError("Invalid username or password.")

    user.failed_login_attempts = 0
    user.last_login_at_utc = _utc_now_iso()
    db.session.flush()
    return user_view(user.ulid)


__all__ = [
    "admin_reset_password",
    "authenticate",
    "any_admin_account_exists",
    "bootstrap_first_admin",
    "change_own_password",
    "create_account",
    "get_auth_failure_view",
    "get_user_roles",
    "get_user_view",
    "list_all_role_codes",
    "list_user_views",
    "lock_account",
    "set_account_active",
    "set_account_roles",
    "set_password",
    "unlock_account",
    "user_view",
]
