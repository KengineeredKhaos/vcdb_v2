# tests/conftest.py
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from flask import Flask
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db
from app.lib.ids import new_ulid


@pytest.fixture(scope="session")
def app():
    app = create_app({"TESTING": True})

    # Force final runtime config (after create_app has done all its loading)
    app.config.update(
        TESTING=True,
        PROPAGATE_EXCEPTIONS=True,  # pytest gets real tracebacks, not 500 JSON
        SECRET_KEY="test-secret",
        WTF_CSRF_ENABLED=False,  # JSON smoke tests shouldn't need CSRF
        WTF_CSRF_CHECK_DEFAULT=False,
    )
    app.testing = True

    # Remove test sqlite file at session start (if sqlite)
    with app.app_context():
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if uri.startswith("sqlite:///"):
            path = Path(uri.replace("sqlite:///", ""))
            if path.exists():
                path.unlink()

    return app


@pytest.fixture(scope="session")
def app_ctx(app):
    with app.app_context():
        yield


@pytest.fixture(scope="session")
def engine(app_ctx) -> Engine:
    eng = db.engine

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
    Build schema once per test session using Alembic migrations.
    """
    alembic_upgrade()
    yield


@pytest.fixture(autouse=True)
def _db_session_per_test(app_ctx, engine):
    """
    Run each test inside a transaction + SAVEPOINT; allow commits safely.
    """
    connection = engine.connect()
    outer = connection.begin()

    options = dict(bind=connection, binds={})
    maker = getattr(db, "create_scoped_session", None) or getattr(
        db, "_make_scoped_session"
    )
    try:
        scoped = maker(options=options)
    except TypeError:
        scoped = maker(options)

    old_session = db.session
    db.session = scoped

    sess = scoped()
    sess.begin_nested()

    @event.listens_for(sess, "after_transaction_end")
    def _restart_savepoint(session, transaction):
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


@pytest.fixture(scope="session", autouse=True)
def bootstrap_test_db(app):
    """
    Build schema + seed baseline ONCE for the entire test session.
    This must live in conftest so it runs even when you execute a single file.
    """
    with app.app_context():
        # call your bootstrap seeder here
        # (best: refactor app/cli_seed.py so it exposes seed_bootstrap_impl)
        from app.cli_seed import seed_bootstrap_impl

        seed_bootstrap_impl(
            fresh=True,
            force=True,
            faker_seed=1337,
            customers=2,
            resources=1,
            sponsors=1,
        )


@pytest.fixture(autouse=True)
def _reset_policy_cache():
    try:
        from app.extensions import policies

        policies._CACHE.clear()  # type: ignore[attr-defined]
        policies._CATALOG = None  # type: ignore[attr-defined]
    except Exception:
        pass
    yield


@pytest.fixture
def ulid() -> Callable[[], str]:
    def _make() -> str:
        return new_ulid()

    return _make


@pytest.fixture
def client(app: Flask):
    return app.test_client()


@pytest.fixture
def staff_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "staff"})
    return client


def pytest_configure(config):
    config.addinivalue_line("markers", "readonly: marks test as read-only")
    config.addinivalue_line(
        "markers", "writes: marks test as performing writes"
    )
