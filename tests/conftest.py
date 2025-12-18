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

    # Start each pytest session with a fresh file DB (avoids stale schema/data)
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = test_db_path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

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


# --- Engine + test DB build once per session -------------------------------


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
def schema_once(app_ctx):
    """
    Create schema directly from SQLAlchemy models (no Alembic).
    """
    # Ensure at least the models you test against are imported so metadata is populated.
    # (Your smoke test imports Fund, but this makes it explicit and future-proof.)
    from app.slices.finance import models as _finance_models  # noqa: F401

    db.drop_all()
    db.create_all()


# --- Function-scoped transactional safety nets --------------------------------


@pytest.fixture(autouse=True)
def _db_session_per_test(app_ctx, engine):
    """
    Each test runs inside an outer transaction + a SAVEPOINT.
    Tests may call commit(); we keep isolation by restarting the SAVEPOINT.
    """
    from sqlalchemy import event

    connection = engine.connect()
    outer = connection.begin()

    options = dict(bind=connection, binds={})
    scoped = db.create_scoped_session(options=options)

    old_session = db.session
    db.session = scoped

    # Start a nested transaction (SAVEPOINT)
    sess = scoped()
    sess.begin_nested()

    @event.listens_for(sess, "after_transaction_end")
    def _restart_savepoint(session, transaction):
        # If the SAVEPOINT ended (e.g., via commit), reopen it
        if transaction.nested and not transaction._parent.nested:
            session.begin_nested()

    try:
        yield scoped
    finally:
        try:
            scoped.remove()
        except Exception:
            pass

        db.session = old_session

        try:
            outer.rollback()
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
