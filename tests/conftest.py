# tests/conftest.py
from __future__ import annotations

import os

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db

# --- Session-wide app ---------------------------------------------------------


@pytest.fixture(scope="session")
def app() -> Flask:
    """
    Build a Flask app for the test session using TestConfig.
    Also points SQLALCHEMY_DATABASE_URI at a temp sqlite file unless
    already set by env (e.g., your vcdb-test alias).
    """
    # Default to a file-backed DB at app/instance/test.db for inspection + determinism.
    inst_dir = os.path.abspath(os.path.join("app", "instance"))
    os.makedirs(inst_dir, exist_ok=True)
    test_db_path = os.path.join(inst_dir, "test.db")
    os.environ.setdefault(
        "SQLALCHEMY_DATABASE_URI", f"sqlite:///{test_db_path}"
    )
    os.environ.setdefault("VCDB_ENV", "testing")

    flask_app = create_app("config.TestConfig")
    # Force it so tests & app agree:
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = os.environ[
        "SQLALCHEMY_DATABASE_URI"
    ]
    return flask_app


@pytest.fixture(scope="session")
def app_ctx(app: Flask):
    """
    Push a single application context for the entire test session.
    Anything that needs current_app / db.engine can rely on this being active.
    """
    ctx = app.app_context()
    ctx.push()
    try:
        yield ctx
    finally:
        ctx.pop()


# --- Engine + DB migration once per session -----------------------------------


@pytest.fixture(scope="session")
def engine(app_ctx) -> Engine:  # depends on app_ctx so current_app is present
    """
    Provide the SQLAlchemy Engine bound to our Flask app and ensure
    SQLite foreign keys are enforced for every connection.
    """
    eng = db.engine  # now safe: we have current_app via app_ctx

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        try:
            dbapi_conn.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass

    return eng


@pytest.fixture(scope="session", autouse=True)
def migrate_once(app_ctx, engine):
    """
    Run Alembic upgrade exactly once for the session.
    """
    from flask_migrate import upgrade as alembic_upgrade

    # Create all tables via Alembic migration
    alembic_upgrade()

    # Optional: sanity print to help debugging
    from sqlalchemy import inspect

    print("[TEST TABLES] first 10:", inspect(engine).get_table_names()[:10])


# --- Function-scoped transactional safety nets --------------------------------


@pytest.fixture(autouse=True)
def _db_session_per_test(app_ctx, engine):
    """
    For each test, run all ORM work inside a single DB transaction that is rolled
    back at the end of the test.

    Pattern:
        connection = engine.connect()
        transaction = connection.begin()
        session = db.create_scoped_session(bind=connection)
        db.session = session
        yield
        rollback + close

    Effects:
        - Tests can freely use `db.session.add/commit/flush` without worrying
          about nesting `begin()` calls.
        - Any data written during a test is rolled back when the test finishes.
        - The underlying schema is managed once per session via Alembic in
          the `migrate_once` fixture.
    """
    # 1. Open a dedicated connection for this test
    connection = engine.connect()
    transaction = connection.begin()

    # 2. Bind a new scoped session to this connection
    options = dict(bind=connection, binds={})
    session = db.create_scoped_session(options=options)

    # 3. Swap out the global session used by the app
    old_session = db.session
    db.session = session

    try:
        yield session
    finally:
        # 4. Tear down: remove session, rollback transaction, close connection
        try:
            session.remove()
        except Exception:
            pass

        db.session = old_session

        try:
            transaction.rollback()
        except Exception:
            pass

        try:
            connection.close()
        except Exception:
            pass


# --- Marks (if you prefer to keep warnings away without touching pytest.ini) ---


def pytest_configure(config):
    # Allow using @pytest.mark.readonly and @pytest.mark.writes without warnings
    config.addinivalue_line("markers", "readonly: marks test as read-only")
    config.addinivalue_line(
        "markers", "writes: marks test as performing writes"
    )
