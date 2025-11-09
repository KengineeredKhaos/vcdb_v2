# tests/conftest.py
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

# IMPORTANT: import the app factory and db after env vars are set
os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("APP_MODE", "testing")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from flask import Flask  # noqa: E402
from flask_migrate import upgrade  # noqa: E402

# --------------------------------------------------------------------------------------
# Session-scoped app + database setup
#   - Uses a single temp-file SQLite DB for the whole test session (stable across conns)
#   - Runs Alembic upgrade ONCE, then seeds canonical minimal data
#   - Provides a request/app context for tests that need current_app
# --------------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _sqlite_uri_file(tmp_path_factory) -> str:
    tmp_dir = tmp_path_factory.mktemp("db")
    uri = f"sqlite:///{tmp_dir}/test.sqlite"
    os.environ["SQLALCHEMY_DATABASE_URI"] = uri
    return uri


@pytest.fixture(scope="session")
def app(_sqlite_uri_file) -> Flask:
    flask_app = create_app("config.TestConfig")
    # force the same URI we put in env
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["SQLALCHEMY_DATABASE_URI"]

    # Foreign keys ON for every SQLite connection (safe & helpful)
    @event.listens_for(db.engine, "connect")  # type: ignore[arg-type]
    def _fk_on(dbapi_conn, _):
        try:
            dbapi_conn.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass

    with flask_app.app_context():
        # Make sure all models are imported before migrate sees them
        import app.extensions.models_registry  # noqa: F401

        # Run migrations once per session
        upgrade()

        # sanity check core tables
        from sqlalchemy import inspect
        tables = set(inspect(db.engine).get_table_names())
        required = {
            "gov_canonical_state",
            "auth_user",
            "ledger_event",
        }
        missing = required - tables
        if missing:
            raise RuntimeError(f"Missing tables after upgrade: {sorted(missing)}")

        # Seed minimal canon data (same code your CLI uses)
        try:
            from app.seeds.core import seed_canon_minimal
            seed_canon_minimal()
        except Exception:
            # keep seeds optional if not wired yet
            pass

    return flask_app


@pytest.fixture(scope="session")
def engine(app: Flask) -> Engine:
    # Use the app's engine; do NOT put query_only here (that leaks across tests)
    return db.engine


# --------------------------------------------------------------------------------------
# Function-scoped DB session fixture
#   - Each test runs in its own SAVEPOINT and is rolled back automatically
#   - No need to wrap every test; this is opt-out clean
# --------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def db_session(app: Flask) -> Iterator[None]:
    """Wrap every test in a transaction+savepoint and roll it back."""
    connection = db.engine.connect()
    trans = connection.begin()
    session = db.create_scoped_session(options={"bind": connection, "binds": {}})

    old_session = db.session
    db.session = session  # type: ignore[assignment]

    try:
        yield
        # no commit; tests should assert effects, not persist them
    finally:
        session.remove()
        db.session = old_session  # type: ignore[assignment]
        trans.rollback()
        connection.close()


# --------------------------------------------------------------------------------------
# Read-only / Writable context managers for specific test sections
#   - Use with_readonly_session() for pure-GET contract smoke checks
#   - Use with_writable_session() to temporarily allow commits (e.g., seeds in-test)
# --------------------------------------------------------------------------------------
@contextlib.contextmanager
def _sqlite_query_only_on(conn):
    conn.exec_driver_sql("PRAGMA query_only = ON;")
    try:
        yield
    finally:
        conn.exec_driver_sql("PRAGMA query_only = OFF;")


@pytest.fixture
def with_readonly_session(engine: Engine):
    """Context manager factory: per-connection read-only mode (SQLite)."""
    @contextlib.contextmanager
    def _ctx():
        with engine.connect() as conn:
            with _sqlite_query_only_on(conn):
                yield
    return _ctx


@pytest.fixture
def with_writable_session(engine: Engine):
    """Context manager factory: explicit writable window (use sparingly)."""
    @contextlib.contextmanager
    def _ctx():
        with engine.connect() as conn:
            # ensure writable
            conn.exec_driver_sql("PRAGMA query_only = OFF;")
            yield
    return _ctx


# --------------------------------------------------------------------------------------
# Optional: test marks to auto-enforce read-only for a test
#   - @pytest.mark.readonly will run the whole test body under PRAGMA query_only=ON
# --------------------------------------------------------------------------------------
def pytest_runtest_call(item):
    if "readonly" in item.keywords:
        engine = item.funcargs.get("engine")
        if engine is None:
            return  # engine not requested; skip auto wrapper
        # wrap the actual call to the test function
        orig_func = item.obj

        def _wrapped(*args, **kwargs):
            with engine.connect() as conn:
                with _sqlite_query_only_on(conn):
                    return orig_func(*args, **kwargs)

        item.obj = _wrapped  # type: ignore[attr-defined]
