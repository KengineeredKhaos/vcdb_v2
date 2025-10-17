# app/extensions/__init__.py
from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable, Dict, Iterable, Optional

from flask import session
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

# -----------------------
# Core singletons
# -----------------------
login_manager = LoginManager()
csrf = CSRFProtect()
db = SQLAlchemy()
migrate = Migrate()


# -----------------
# JSON / CSV Handler
# -----------------
def _cast_json_or_iter(v):
    if v is None:
        return ()
    if isinstance(v, (list, tuple, set)):
        return tuple(v)
    s = str(v).strip()
    if s.startswith("[") or s.startswith("{"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return tuple(parsed)
        except Exception:
            pass
    # fallback: CSV
    return tuple(p.strip() for p in s.split(",") if p.strip())


# -----------------
# Bootstrap Initialization
# -----------------


def ensure_initialized() -> None:
    """
    Idempotent; call from app factory after blueprints/contracts are wired.
    Ensures defaults are bootstrapped into DB, then refreshes the cache.
    """
    global _INIT
    if _INIT:
        return


# -----------------
# Entity API
# -----------------
class _EntityAPI:
    def __init__(self):
        self._impl = {}

    def register(self, **impl):
        self._impl.update(impl)

    # stable signatures
    def ensure_person(self, **kw):
        return self._impl["ensure_person"](**kw)

    def ensure_org(self, **kw):
        return self._impl["ensure_org"](**kw)

    def upsert_contacts(self, **kw):
        return self._impl["upsert_contacts"](**kw)

    def upsert_address(self, **kw):
        return self._impl["upsert_address"](**kw)

    def ensure_role(self, **kw):
        return self._impl["ensure_role"](**kw)


entity_api = _EntityAPI()


# -----------------
# Entity read-side Facade
# -----------------


class EntityReadFacade:
    def __init__(self):
        self._impl = {}

    def register(self, **kw):
        self._impl.update(kw)

    def list_people_with_role(self, role_code: str, page: int, per: int):
        fn = self._impl.get("list_people_with_role")
        if not fn:
            raise RuntimeError(
                "entity_read.list_people_with_role not registered"
            )
        return fn(role_code=role_code, page=page, per=per)

    def person_view(self, person_id: str):
        fn = self._impl.get("person_view")
        if not fn:
            raise RuntimeError("entity_read.person_view not registered")
        return fn(person_id=person_id)


entity_read = EntityReadFacade()


# -----------------------------------------
# Auth context shim: current_actor_id (ULID)
# -----------------------------------------


def current_actor_id() -> Optional[str]:
    """
    Return a stable ULID for the *actor* in this session.
    In prod you might store an actor ULID on the user row; for dev we cache in session.
    """
    if not getattr(current_user, "is_authenticated", False):
        return None
    key = f"actor_ulid:u{getattr(current_user, 'id', 'anon')}"
    if key not in session:
        session[key] = new_ulid()
    return session[key]


# -----------------------
# Enforcer registry
# -----------------------


# Enforcer registry (pluggable)
class _Enforcers:
    def __init__(self) -> None:
        self._map: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._map[name] = fn

    def __getattr__(self, name: str):
        try:
            return self._map[name]
        except KeyError:
            raise PolicyError(f"enforcer '{name}' not registered")


enforcers = _Enforcers()


# -----------------
# Role codes helper
# -----------------
def _cast_csv_or_iter(v) -> tuple[str, ...]:
    if isinstance(v, (list, tuple, set)):
        return tuple(v)
    if v is None:
        return ()
    return tuple(s.strip() for s in str(v).split(",") if s.strip())


def allowed_role_codes() -> tuple[str, ...]:
    """
    Domain roles are owned by Governance.
    Read via the public contract (no DB here).
    """
    try:
        from app.extensions.contracts.governance import v1 as gov

        roles = gov.get_domain_roles()  # returns objects with .code
        codes = [r.code for r in roles if getattr(r, "code", None)]
        return (
            tuple(codes)
            if codes
            else ("customer", "resource", "sponsor", "governor")
        )
    except Exception:
        # Conservative fallback if contract not wired yet
        return ("customer", "resource", "sponsor", "governor")


# -----------------------
# App init
# -----------------------


def init_extensions(app):
    # Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"

    # CSRF
    csrf.init_app(app)

    # SQLAlchemy
    db.init_app(app)

    # Global listener: fires for any SQLAlchemy Engine
    # (only applies if DBAPI is sqlite3)
    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    # Alembic/Migrations
    migrate.init_app(app, db)

    return app


# -----------------
# Export Hygiene
# -----------------
