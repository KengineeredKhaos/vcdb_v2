# app/extensions/__init__.py
from __future__ import annotations

import json
import sqlite3
from typing import Any

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .auth_ctx import current_actor_id
from .entity_api import entity_api
from .entity_read import entity_read

# -----------------------
# Core singletons
# -----------------------
login_manager = LoginManager()
csrf = CSRFProtect()
db = SQLAlchemy()
migrate = Migrate()


# -----------------
# JSON / CSV Handler
# commented out
# until we determine
# suitability
# -----------------
"""
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
"""

# -----------------
# Bootstrap Initialization
# -----------------

# -- module init guard
_INIT: bool = False


def ensure_initialized() -> None:
    """
    Idempotent no-op for now; keep as a hook if you later add bootstraps.
    """
    global _INIT
    if _INIT:
        return
    _INIT = True  # <<< set on first call


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
        from app.extensions.contracts import governance_v2 as gov

        roles = gov.get_domain_roles()  # returns objects with .code

    except Exception:
        try:
            # fallback to older v1, if present
            from app.extensions.contracts.governance import (
                v1 as gov,  # type: ignore
            )

            roles = gov.get_domain_roles()
        except Exception:
            return ("customer", "resource", "sponsor", "governor")

    codes = [r.code for r in roles if getattr(r, "code", None)]
    return (
        tuple(codes)
        if codes
        else ("customer", "resource", "sponsor", "governor")
    )


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

__all__ = [
    "login_manager",
    "csrf",
    "db",
    "migrate",
    "init_extensions",
    "entity_api",
    "entity_read",
    "current_actor_id",
]
