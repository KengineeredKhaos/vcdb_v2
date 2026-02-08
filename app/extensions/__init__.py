# app/extensions/__init__.py

"""
Extensions: cross-slice glue (policies, enforcers, and contracts).

This package wires VCDB slices together via JSON-based governance
policies, runtime enforcers, and versioned contract modules under
`extensions/contracts`.

For a higher-level overview (how policies, schemas, and contracts fit
together), see docs/extensions.md.

The balance of this file is SQLite Database/SQLAlchemy wiring.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event

# -----------------
# Singletons
# (imported everywhere)
# -----------------

db = SQLAlchemy(
    session_options={
        "autoflush": False,
        "expire_on_commit": False,
    }
)
migrate = Migrate(compare_type=True)  # keep compare_type for SQLite dev
login_manager = LoginManager()
csrf = CSRFProtect()


# -----------------
# Engine tuning (SQLite)
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
        "PRAGMA synchronous=NORMAL;",  # safe + faster than FULL
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
    eng = db.engine  # requires an app context

    # Idempotence flag attached to the engine object.
    if getattr(eng, "_vcdb_sqlite_listeners_installed", False):
        return

    @event.listens_for(eng, "connect")
    def _on_connect(dbapi_conn, _rec) -> None:
        if isinstance(dbapi_conn, sqlite3.Connection):
            _tune_sqlite_connection(dbapi_conn)

    eng._vcdb_sqlite_listeners_installed = True  # type: ignore[attr-defined]


# -----------------
# Init entrypoint
# -----------------


def init_extensions(flask_app: Flask) -> None:
    """
    Bind core Flask extensions to the app and finalize DB engine hooks.

    Responsibilities:
    - Bind SQLAlchemy, Flask-Migrate, and Flask-Login.
    - Import all models once so db.metadata is complete.
    - Install SQLite PRAGMAs via a single connect-listener.
    - Register teardown handlers so sessions never commit implicitly and
      are always removed at the end of the request/app context.

    CSRF, Jinja settings, context processors, and error handlers are owned
    by the application factory (app/__init__.py), not this module.
    """
    # --- Bind Flask extensions ---
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)
    login_manager.login_view = "auth.login"
    # endpoint string; adjust if needed

    # --- Finalize DB engine hooks & ensure models are loaded ---
    with flask_app.app_context():
        # Ensure all models are imported exactly once so db.metadata is complete.
        # This module can be a simple registry that imports each slice's models.
        import app.extensions.models_registry  # noqa: F401

        _install_sqlite_listeners_once(flask_app)

    # --- Idempotent teardown wiring (dev reload / tests safe) ---
    if getattr(flask_app, "_vcdb_teardowns_installed", False):
        return

    def _teardown_request(exc: BaseException | None) -> None:  # type: ignore[override]
        """
        Request-level cleanup:
        - Roll back the session on exceptions.
        - Never auto-commit on success (services must commit explicitly).
        - Always remove the scoped Session.
        """
        if exc is not None:
            try:
                db.session.rollback()
            except Exception:
                pass
        try:
            db.session.remove()
        except Exception:
            pass

    def _teardown_appcontext(exc: BaseException | None) -> None:
        """
        App-context-level safety net; always remove the scoped Session.
        """
        try:
            db.session.remove()
        except Exception:
            pass

    flask_app.teardown_request(_teardown_request)
    flask_app.teardown_appcontext(_teardown_appcontext)
    flask_app._vcdb_teardowns_installed = True  # type: ignore[attr-defined]
