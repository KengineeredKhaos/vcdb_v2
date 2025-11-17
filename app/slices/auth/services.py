# app/slices/auth/services.py
from __future__ import annotations

from hashlib import sha256
from typing import List, Tuple

from sqlalchemy import asc
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.extensions.event_bus import emit
from app.lib.chrono import utcnow_naive
from app.lib.ids import new_ulid
from app.lib.utils import normalize_email, validate_email

from .models import Role, User


# Domain-local error for 404 mapping in routes
class NotFound(Exception):
    pass


# ---- Role helpers ----
def ensure_role(code: str, description: str | None = None) -> dict:
    code = (code or "").strip().lower()
    if not code:
        raise ValueError("role code required")
    r = db.session.query(Role).filter_by(code=code).one_or_none()
    if not r:
        r = Role(code=code, description=description or code)
        db.session.add(r)
        db.session.commit()
    elif description and r.description != description:
        r.description = description
        db.session.commit()
    return {
        "code": r.code,
        "description": r.description,
        "is_active": r.is_active,
    }


def list_roles() -> list[dict]:
    rows = db.session.query(Role).order_by(asc(Role.code)).all()
    return [
        {
            "code": r.code,
            "description": r.description,
            "is_active": r.is_active,
        }
        for r in rows
    ]


# ---- User lifecycle ----
def create_user(
    *,
    username: str,
    email: str,
    password: str,
    entity_ulid: str | None = None,
) -> dict:
    username = (username or "").strip().lower()
    email = normalize_email(email)
    validate_email(email)
    if (
        db.session.query(User)
        .filter((User.username == username) | (User.email == email))
        .first()
    ):
        raise ValueError("username or email already exists")
    u = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        entity_ulid=entity_ulid,
    )
    db.session.add(u)
    db.session.commit()
    # Actor is unclear here (self vs admin).
    # Use the new user as actor for now.
    emit(
        domain="auth",
        operation="user.created",
        request_id=new_ulid(),
        actor_ulid=u.ulid,
        target_ulid=u.ulid,
        changed={"username": u.username, "email": u.email},
    )
    return user_view(u.ulid)


LOCKOUT_THRESHOLD = 5


def authenticate(username_or_email: str, password: str) -> dict:
    ident = (username_or_email or "").strip().lower()
    q = db.session.query(User).options(joinedload(User.roles))
    u = q.filter(
        (User.username == ident) | (User.email == ident)
    ).one_or_none()

    # Unknown / inactive / locked
    if not u or not u.is_active or u.is_locked:
        # PII-safe invalid-ident event; schema requires actor_ulid, use a fresh ULID (attempt id)
        ident_fpr = sha256(ident.encode("utf-8")).hexdigest()[:12]
        emit(
            domain="auth",
            operation="login.invalid_ident",
            request_id=new_ulid(),
            actor_ulid=new_ulid(),  # synthetic actor for unknown actor
            target_ulid=new_ulid(),  # synthetic target for unknown actor
            refs={"ident_fpr": ident_fpr},
        )
        raise ValueError("Invalid credentials")

    # Bad password
    if not check_password_hash(u.password_hash, password):
        u.failed_login_attempts = (u.failed_login_attempts or 0) + 1
        if u.failed_login_attempts >= LOCKOUT_THRESHOLD:
            u.is_locked = True
        db.session.commit()

        emit(
            domain="auth",
            operation="login.failed",
            request_id=new_ulid(),
            actor_ulid=u.ulid,
            target_ulid=u.ulid,
            changed={
                "failed_login_attempts": u.failed_login_attempts,
                "is_locked": u.is_locked,
            },
        )
        raise ValueError("Invalid credentials")

    # Success
    u.failed_login_attempts = 0
    u.last_login_at_utc = utcnow_naive()
    db.session.commit()

    emit(
        domain="auth",
        operation="login.success",
        request_id=new_ulid(),
        actor_ulid=u.ulid,
        target_ulid=u.ulid,
    )
    return user_view(u.ulid)


def change_password(
    user_ulid: str, *, old_password: str, new_password: str
) -> None:
    u = db.session.get(User, user_ulid)
    if not u or not check_password_hash(u.password_hash, old_password):
        raise ValueError("invalid credentials")
    u.password_hash = generate_password_hash(new_password)
    db.session.commit()
    emit(
        domain="auth",
        operation="password.changed",
        request_id=new_ulid(),
        actor_ulid=user_ulid,
        target_ulid=user_ulid,
    )


# ---- RBAC management ----
def assign_role(*, user_ulid: str, role_code: str) -> None:
    role_code = (role_code or "").strip().lower()
    u = db.session.get(User, user_ulid)
    r = (
        db.session.query(Role)
        .filter_by(code=role_code, is_active=True)
        .one_or_none()
    )
    if not u or not r:
        raise ValueError("user or role not found")
    if any(rr.ulid == r.ulid for rr in u.roles):
        return
    u.roles.append(r)
    db.session.commit()
    emit(
        domain="auth",
        operation="role.assigned",
        request_id=new_ulid(),
        actor_ulid=u.ulid,  # if you prefer, pass the admin actor here
        target_ulid=u.ulid,
        changed={"role": r.code},
    )


def remove_role(*, user_ulid: str, role_code: str) -> None:
    role_code = (role_code or "").strip().lower()
    u = db.session.get(User, user_ulid)
    if not u:
        return
    u.roles[:] = [r for r in u.roles if r.code != role_code]
    db.session.commit()
    emit(
        domain="auth",
        operation="role.removed",
        request_id=new_ulid(),
        actor_ulid=user_ulid,  # if you prefer, pass the admin actor here
        target_ulid=user_ulid,
        changed={"role": role_code},
    )


def set_account_roles(
    *,
    account_ulid: str,
    roles: list[str],
    actor_entity_ulid: str | None = None,
) -> None:
    roles = sorted({(r or "").strip().lower() for r in roles if r})
    u = db.session.get(User, account_ulid)
    if not u:
        raise NotFound("user not found")
    existing = {r.code for r in (u.roles or [])}
    to_add = set(roles) - existing
    to_drop = existing - set(roles)
    for r in to_add:
        assign_role(user_ulid=account_ulid, role_code=r)
    for r in to_drop:
        remove_role(user_ulid=account_ulid, role_code=r)


# ---- projections ----
def user_view(user_ulid: str) -> dict:
    u = (
        db.session.query(User)
        .options(joinedload(User.roles))
        .filter_by(ulid=user_ulid)
        .one()
    )
    return {
        "ulid": u.ulid,
        "username": u.username,
        "email": u.email,
        "roles": [r.code for r in u.roles],
        "entity_ulid": u.entity_ulid,
        "is_active": u.is_active,
        "is_locked": u.is_locked,
        "last_login_at_utc": u.last_login_at_utc,
        "created_at_utc": u.created_at_utc,
        "updated_at_utc": u.updated_at_utc,
    }


def list_users(page: int = 1, per: int = 50) -> Tuple[List[dict], int]:
    page = max(int(page or 1), 1)
    per = min(max(int(per or 50), 1), 200)
    q = db.session.query(User).order_by(asc(User.username))
    total = q.count()
    rows = q.offset((page - 1) * per).limit(per).all()
    return [user_view(u.ulid) for u in rows], total
