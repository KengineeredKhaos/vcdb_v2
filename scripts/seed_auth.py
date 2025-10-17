# scripts/seed_auth.py
from werkzeug.security import generate_password_hash
from app.extensions import db
from app.lib.ids import new_ulid
from app.lib.chrono import now_iso8601_ms
from app.slices.auth.models import User, Role, UserRole

AUTH_ROLES = [
    ("user", "Standard user"),
    ("auditor", "Read-only"),
    ("admin", "Administrator"),
]


def upsert_role(code: str, description: str, is_active: bool = True) -> Role:
    r = Role.query.filter_by(code=code).one_or_none()
    if not r:
        r = Role(
            ulid=new_ulid(),
            code=code,
            description=description,
            is_active=is_active,
            created_at_utc=now_iso8601_ms(),
            updated_at_utc=now_iso8601_ms(),
        )
        db.session.add(r)
    else:
        r.description = description
        r.is_active = is_active
        r.updated_at_utc = now_iso8601_ms()
    return r


def ensure_admin_user() -> User:
    u = User.query.filter_by(username="admin").one_or_none()
    if not u:
        u = User(
            ulid=new_ulid(),
            username="admin",
            email="admin@example.test",
            password_hash=generate_password_hash("admin"),
            is_active=True,
            is_locked=False,
            failed_login_attempts=0,
            created_at_utc=now_iso8601_ms(),
            updated_at_utc=now_iso8601_ms(),
        )
        db.session.add(u)
    return u


def ensure_user_role(user: User, role: Role):
    link = UserRole.query.filter_by(
        user_ulid=user.ulid, role_ulid=role.ulid
    ).one_or_none()
    if not link:
        link = UserRole(
            ulid=new_ulid(),
            user_ulid=user.ulid,
            role_ulid=role.ulid,
        )
        db.session.add(link)


def run():
    roles = {code: upsert_role(code, desc) for code, desc in AUTH_ROLES}
    admin = ensure_admin_user()
    ensure_user_role(admin, roles["admin"])
    db.session.commit()
    print("✓ auth seeded (roles + admin user)")
