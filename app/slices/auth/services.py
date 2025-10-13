# app/slices/auth/services.py
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from sqlalchemy import asc
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, event_bus
from app.lib.chrono import utc_now
from app.lib.utils import (
    normalize_email,
    validate_email,
)

from .models import Role, User, UserRole

# Keep RBAC roles here (auth slice owns them). Domain roles live in entity/governance.
RBAC_ALLOWED = {"user", "auditor", "admin"}

# ---------- helpers ----------


def _ensure_reqid(request_id: Optional[str]) -> str:
    if not request_id or not str(request_id).strip():
        raise ValueError("request_id must be non-empty")
    return str(request_id)


def _hash_pw(raw: str) -> str:
    if not raw or len(raw) < 8:
        raise ValueError("password must be at least 8 characters")
    # Same scheme you’ve used elsewhere
    return generate_password_hash(raw, method="pbkdf2:sha256", salt_length=16)


# ---------- role ops ----------


def ensure_role(code: str, description: Optional[str] = None) -> str:
    """Idempotently ensure an RBAC role exists; return role_ulid."""
    code = (code or "").strip().lower()
    if code not in RBAC_ALLOWED:
        raise ValueError(f"RBAC role '{code}' not allowed")
    r = db.session.query(Role).filter_by(code=code).first()
    if r:
        if description is not None:
            r.description = description or None
            db.session.commit()
        return r.ulid
    r = Role(code=code, description=description or None)
    db.session.add(r)
    db.session.commit()
    return r.ulid


def assign_role(
    *,
    user_ulid: str,
    role_code: str,
    request_id: str,
    actor_id: Optional[str],
) -> bool:
    """Attach a role to a user (idempotent)."""
    _ensure_reqid(request_id)
    role_ulid = ensure_role(role_code)
    exists = (
        db.session.query(UserRole)
        .filter_by(user_ulid=user_ulid, role_ulid=role_ulid)
        .first()
    )
    if exists:
        return False
    db.session.add(UserRole(user_ulid=user_ulid, role_ulid=role_ulid))
    db.session.commit()

    event_bus.emit(
        type="auth.role.assigned",
        slice="auth",
        operation="assign",
        actor_id=actor_id,
        target_id=user_ulid,
        request_id=request_id,
        happened_at=utc_now(),
        refs={"role_code": role_code},
    )
    return True


def remove_role(
    *,
    user_ulid: str,
    role_code: str,
    request_id: str,
    actor_id: Optional[str],
) -> bool:
    """Detach a role from a user (idempotent)."""
    _ensure_reqid(request_id)
    r = db.session.query(Role).filter_by(code=role_code).first()
    if not r:
        return False
    link = (
        db.session.query(UserRole)
        .filter_by(user_ulid=user_ulid, role_ulid=r.ulid)
        .first()
    )
    if not link:
        return False
    db.session.delete(link)
    db.session.commit()

    event_bus.emit(
        type="auth.role.removed",
        slice="auth",
        operation="remove",
        actor_id=actor_id,
        target_id=user_ulid,
        request_id=request_id,
        happened_at=utc_now(),
        refs={"role_code": role_code},
    )
    return True


# ---------- user ops ----------


def create_user(
    *,
    username: str,
    password: str,
    email: Optional[str],
    entity_ulid: Optional[str],
    request_id: str,
    actor_id: Optional[str],
) -> str:
    """
    Create a user (active by default). Username unique, email optional/unique.
    Returns user_ulid.
    """
    _ensure_reqid(request_id)

    u = (username or "").strip().lower()
    if not u:
        raise ValueError("username is required")

    em = normalize_email(email) if email is not None else None
    if email is not None and em and not validate_email(em):
        raise ValueError("invalid email")

    if db.session.query(User).filter_by(username=u).first():
        raise ValueError("username already exists")
    if em and db.session.query(User).filter_by(email=em).first():
        raise ValueError("email already exists")

    user = User(
        username=u,
        email=em,
        password_hash=_hash_pw(password),
        entity_ulid=entity_ulid or None,
        is_active=True,
        is_locked=False,
    )
    db.session.add(user)
    db.session.commit()

    event_bus.emit(
        type="auth.user.created",
        slice="auth",
        operation="insert",
        actor_id=actor_id,
        target_id=user.ulid,
        request_id=request_id,
        happened_at=utc_now(),
        changed_fields={
            "username": u,
            "email": em,
            "entity_ulid": entity_ulid,
        },
    )
    return user.ulid


def set_password(
    *,
    user_ulid: str,
    new_password: str,
    request_id: str,
    actor_id: Optional[str],
) -> None:
    _ensure_reqid(request_id)
    user = db.session.get(User, user_ulid)
    if not user:
        raise ValueError("user not found")
    user.password_hash = _hash_pw(new_password)
    db.session.commit()
    event_bus.emit(
        type="auth.user.password_changed",
        slice="auth",
        operation="update",
        actor_id=actor_id,
        target_id=user_ulid,
        request_id=request_id,
        happened_at=utc_now(),
    )


def authenticate(
    *, username: str, password: str, request_id: str
) -> Optional[str]:
    """Return user_ulid on success, None on failure. (No session mgmt here.)"""
    _ensure_reqid(request_id)
    u = (
        db.session.query(User)
        .filter_by(username=(username or "").strip().lower())
        .first()
    )
    if not u or not check_password_hash(u.password_hash, password):
        return None
    u.last_login_utc = utc_now()
    db.session.commit()
    return u.ulid


def toggle_active(
    *, user_ulid: str, active: bool, request_id: str, actor_id: Optional[str]
) -> None:
    _ensure_reqid(request_id)
    u = db.session.get(User, user_ulid)
    if not u:
        raise ValueError("user not found")
    u.is_active = bool(active)
    db.session.commit()
    event_bus.emit(
        type="auth.user.toggled_active",
        slice="auth",
        operation="update",
        actor_id=actor_id,
        target_id=user_ulid,
        request_id=request_id,
        happened_at=utc_now(),
        changed_fields={"is_active": u.is_active},
    )


# ---------- views / listings ----------


def user_view(user_ulid: str) -> Optional[dict]:
    u = (
        db.session.query(User)
        .options(joinedload(User.roles))
        .filter(User.ulid == user_ulid)
        .first()
    )
    if not u:
        return None
    return {
        "user_ulid": u.ulid,
        "username": u.username,
        "email": u.email,
        "is_active": u.is_active,
        "is_locked": u.is_locked,
        "last_login_utc": u.last_login_utc,
        "roles": [r.code for r in u.roles],
        "entity_ulid": u.entity_ulid,
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
