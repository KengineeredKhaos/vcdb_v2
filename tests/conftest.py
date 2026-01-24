# tests/conftest.py
from __future__ import annotations

import os
from typing import Callable

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db
from app.lib.ids import new_ulid


# --- Session-wide app ---------------------------------------------------------


@pytest.fixture(scope="session")
def app() -> Flask:
    """Create the Flask app once for the whole test session."""

    # Default to a file-backed DB at app/instance/test.db (easy to inspect).
    inst_dir = os.path.abspath(os.path.join("app", "instance"))
    os.makedirs(inst_dir, exist_ok=True)
    test_db_path = os.path.join(inst_dir, "test.db")

    os.environ.setdefault(
        "SQLALCHEMY_DATABASE_URI", f"sqlite:///{test_db_path}"
    )
    os.environ.setdefault("VCDB_ENV", "testing")

    # Start each pytest session with a fresh file DB (avoid stale schema/data)
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = test_db_path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    flask_app = create_app("config.TestConfig")

    # Force app + tests to agree on DB URI
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = os.environ[
        "SQLALCHEMY_DATABASE_URI"
    ]
    return flask_app


@pytest.fixture(scope="session")
def app_ctx(app: Flask):
    """Push one Flask app context for the entire session."""
    ctx = app.app_context()
    ctx.push()
    try:
        yield ctx
    finally:
        ctx.pop()


# --- Engine + schema build once per session -----------------------------------


@pytest.fixture(scope="session")
def engine(app_ctx) -> Engine:
    """Return SQLAlchemy Engine and enable SQLite foreign keys."""
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
    """Create schema directly from SQLAlchemy models (no Alembic)."""

    # IMPORTANT: import *all* slice models so metadata is populated.
    # If a slice's models aren't imported, db.create_all() won't create its tables.
    from app.slices import (  # noqa: F401
        admin,
        attachments,
        auth,
        calendar,
        customers,
        entity,
        finance,
        governance,
        ledger,
        logistics,
        resources,
        sponsors,
    )

    # Touch models modules explicitly (some slices may not import models in __init__)
    from app.slices.admin import models as _admin_models  # noqa: F401
    from app.slices.attachments import models as _att_models  # noqa: F401
    from app.slices.auth import models as _auth_models  # noqa: F401
    from app.slices.calendar import models as _cal_models  # noqa: F401
    from app.slices.customers import models as _cust_models  # noqa: F401
    from app.slices.entity import models as _ent_models  # noqa: F401
    from app.slices.finance import models as _fin_models  # noqa: F401
    from app.slices.governance import models as _gov_models  # noqa: F401
    from app.slices.ledger import models as _led_models  # noqa: F401
    from app.slices.logistics import models as _log_models  # noqa: F401
    from app.slices.resources import models as _res_models  # noqa: F401
    from app.slices.sponsors import models as _sp_models  # noqa: F401

    db.drop_all()
    db.create_all()


# --- Function-scoped transactional safety net ---------------------------------


@pytest.fixture(autouse=True)
def _db_session_per_test(app_ctx, engine):
    """Run each test inside a transaction + SAVEPOINT; allow commits safely."""
    from sqlalchemy import event

    connection = engine.connect()
    outer = connection.begin()

    options = dict(bind=connection, binds={})

    # Flask-SQLAlchemy 2.x exposed create_scoped_session(); 3.x uses the
    # private _make_scoped_session(). Support both without pinning a version.
    maker = getattr(db, "create_scoped_session", None) or getattr(
        db, "_make_scoped_session"
    )
    try:
        scoped = maker(options=options)
    except TypeError:
        # Some versions accept the dict as a positional arg.
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


# --- Policy cache isolation ---------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_policy_cache():
    """Reset policy loader caches between tests (avoids cross-test bleed)."""
    try:
        from app.extensions import policies

        policies._CACHE.clear()  # type: ignore[attr-defined]
        policies._CATALOG = None  # type: ignore[attr-defined]
    except Exception:
        # If internals change, don't brick the test suite.
        pass
    yield


# --- Handy factories ----------------------------------------------------------


@pytest.fixture
def ulid() -> Callable[[], str]:
    """Generate a new ULID string."""

    def _make() -> str:
        return new_ulid()

    return _make


@pytest.fixture
def client(app: Flask):
    return app.test_client()


@pytest.fixture
def admin_client(client):
    # Stub auth: create_app() reads header X-Auth-Stub.
    client.environ_base.update({"HTTP_X_AUTH_STUB": "admin"})
    return client


@pytest.fixture
def staff_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "staff"})
    return client


@pytest.fixture
def auditor_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "auditor"})
    return client


# --- Marks -------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "readonly: marks test as read-only")
    config.addinivalue_line(
        "markers", "writes: marks test as performing writes"
    )
