# app/extensions/__init__.py
from __future__ import annotations

import sqlite3
from typing import Optional

from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError, generate_csrf
from jinja2 import StrictUndefined
from sqlalchemy import event

# -----------------
# Singletons
# (imported everywhere)
# -----------------

db = SQLAlchemy(session_options={"autoflush": False, "expire_on_commit": False})
migrate = Migrate(compare_type=True)  # keep compare_type for SQLite dev
login_manager = LoginManager()
csrf = CSRFProtect()

# -----------------
# init extensions
# -----------------

def init_extensions(flask_app: Flask) -> None:
    # Bind extensions
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)
    login_manager.login_view = "auth.login"
    csrf.init_app(flask_app)  # <-- enable CSRF

    # Jinja: strict mode
    flask_app.jinja_env.undefined = StrictUndefined

    # Make {{ csrf_token() }} available to ALL templates safely
    @flask_app.context_processor
    def _inject_csrf_token():
        # generate_csrf() needs an app/request ctx; returns "" in testing when disabled
        return {"csrf_token": generate_csrf}

    # Nice error for CSRF failures (programmatic registration avoids decorator binding issues)
    def _handle_csrf_error(e: CSRFError):
        return {
            "error": "csrf_failed",
            "description": getattr(e, "description", "CSRF validation failed."),
        }, 400

    flask_app.register_error_handler(CSRFError, _handle_csrf_error)



# -----------------
# Engine tuning
# (SQLite)
# -----------------

def _tune_sqlite_connection(dbapi_conn: sqlite3.Connection) -> None:
    """
    Apply conservative, production-safe PRAGMAs for SQLite.
    - foreign_keys=ON protects referential integrity (tests rely on this).
    - journal_mode=WAL + synchronous=NORMAL is safe for file-backed DBs.
      (In-memory DB will ignore WAL and that's fine.)
    """
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    # These are best-effort; ignore if not supported (e.g., :memory:)
    for pragma in (
        "PRAGMA journal_mode=WAL;",
        "PRAGMA synchronous=NORMAL;",   # safe + faster than FULL
        "PRAGMA temp_store=MEMORY;",
    ):
        try:
            cur.execute(pragma)
        except Exception:
            pass
    cur.close()


def _install_sqlite_listeners_once(app: Flask) -> None:
    """
    Install connect-listener on the current engine only once.
    This guards against test reboots / factory re-use and dev auto-reload.
    """
    eng = db.engine  # requires an app context (factory already has one)

    # Idempotence flag attached to the engine object.
    if getattr(eng, "_vcdb_sqlite_listeners_installed", False):
        return

    @event.listens_for(eng, "connect")
    def _on_connect(dbapi_conn, _rec) -> None:
        if isinstance(dbapi_conn, sqlite3.Connection):
            _tune_sqlite_connection(dbapi_conn)

    eng._vcdb_sqlite_listeners_installed = True


# -----------------
# Init entrypoint
# -----------------

def init_extensions(flask_app: Flask) -> None:
    """
    Bind extensions to the Flask app, then (inside app context) finalize DB engine hooks.
    Safe to call from tests and dev reloads; everything is idempotent.
    """
    # Bind Flask extensions
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)
    login_manager.login_view = "auth.login"  # endpoint string; adjust if needed

    # Register models with metadata before Alembic / reflection
    # (keeps imports localized to avoid cycles and import-time config reads)
    with flask_app.app_context():
        # Ensure all models are imported exactly once so db.metadata is complete
        import app.extensions.models_registry  # noqa: F401
        _install_sqlite_listeners_once(flask_app)

    # Idempotence guard so we don't double-register handlers on reloads
    if getattr(flask_app, "_vcdb_teardowns_installed", False):
        return

    # Request lifecycle hygiene: never commit implicitly.
    # Roll back on errors; always remove the Session at end of request/appctx.

    def _teardown_request(exc: Optional[BaseException]) -> None:  # type: ignore[override]
        if exc is not None:
            try:
                db.session.rollback()
            except Exception:
                pass
        # We do not auto-commit on success here;
        # commits must be explicit in services.
        # Always dispose the scoped session
        try:
            db.session.remove()
        except Exception:
            pass


    def _teardown_appcontext(exc: Optional[BaseException]) -> None:
        # Safety net at appctx teardown
        try:
            db.session.remove()
        except Exception:
            pass

    # Register handlers programmatically
    # to avoid any decorator name resolution
    flask_app.teardown_request(_teardown_request)
    flask_app.teardown_appcontext(_teardown_appcontext)

    flask_app._vcdb_teardowns_installed = True

