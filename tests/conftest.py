# tests/conftest.py
import contextlib
import logging
import os
import pathlib
import pytest
import sys

from flask_migrate import upgrade as fm_upgrade
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool
from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.lib.ids import new_ulid

from tests.seeds import seed_minimal_party_triplet as _seed_triplet
from tests.support import with_readonly_session


_root = pathlib.Path(__file__).resolve().parents[1]
# prune in-repo venv paths from sys.path for collection/imports
for p in list(sys.path):
    if (("lib/python" in p or "site-packages" in p) and str(_root) in p):
        sys.path.remove(p)

@pytest.fixture()
def cfg(app):
    """Convenience handle for the active Flask config."""
    return app.config


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture
def app_ctx(app):
    """Alias so tests that expect `app_ctx` keep working."""
    return app


@pytest.fixture()
def seed_party_triplet(db_session):
    """
    Returns (entity_ulid, customer_ulid, resource_ulid, sponsor_ulid)
    """
    return _seed_triplet(db_session)


# ------------------------------------------------------------------------------
# Session-wide DB file location (authoritative)
# ------------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _set_writable_sqlite_uri(tmp_path_factory):
    """
    Point tests at a writable sqlite file in a temp dir.
    Session-scoped and does NOT use monkeypatch (so no scope clash).
    """
    dbdir = tmp_path_factory.mktemp("db")
    dbfile = dbdir / "test.sqlite"
    uri = f"sqlite:///{dbfile}"
    os.environ["SQLALCHEMY_DATABASE_URI"] = uri
    os.environ.setdefault("DATABASE_URL", uri)
    return str(dbfile)


@pytest.fixture(scope="session", autouse=True)
def _fresh_sqlite_before_migrations(_set_writable_sqlite_uri):
    """
    Ensure the sqlite file does not exist before Alembic upgrade runs.
    Depends on _set_writable_sqlite_uri to enforce correct ordering.
    """
    p = pathlib.Path(_set_writable_sqlite_uri)
    if p.exists():
        p.unlink()


# ------------------------------------------------------------------------------
# Session-wide app + migration
# ------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    os.environ["FLASK_ENV"] = "testing"
    flask_app = create_app("config.TestConfig")

    # Use an in-memory DB but migrate it once for the whole session
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with flask_app.app_context():
        import app.extensions.models_registry  # ensure models are imported
        from flask_migrate import upgrade
        upgrade()

    return flask_app

@pytest.fixture(scope="session")
def engine(app):
    # Use the same engine the app uses
    eng = db.engine

    # Keep ONLY foreign_keys pragma globally (safe & helpful)
    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        try:
            dbapi_conn.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass

    return eng


# -----------------
# session context
# -----------------

@pytest.fixture(scope="session", autouse=True)
def _session_app_context(app):
    """
    Push a Flask app context for the ENTIRE test session.
    This prevents 'working outside of app context' from imports or other
    session-scoped fixtures that touch current_app/db before tests run.
    """
    ctx = app.app_context()
    ctx.push()
    try:
        yield
    finally:
        ctx.pop()


# ------------------------------------------------------------------------------
# Per-test DB isolation (SAVEPOINT)
# ------------------------------------------------------------------------------

@pytest.fixture()
def db_session(app, engine):
    """Give each test a clean SQLAlchemy session wrapped in a SAVEPOINT."""
    with app.app_context():
        conn = engine.connect()
        trans = conn.begin()  # outer transaction
        # New session bound to this connection
        Session = db.sessionmaker(bind=conn)
        sess = Session()

        # Make db.session point to ours during the test
        old = db.session
        db.session = sess
        try:
            yield sess
        finally:
            # Teardown: close session, rollback, and restore global
            sess.close()
            trans.rollback()
            conn.close()
            db.session = old


# -----------------
# Readonly opt-in
# -----------------

@contextlib.contextmanager
def readonly_connection(engine):
    """Context manager that sets PRAGMA query_only=ON for this ONE connection."""
    conn = engine.connect()
    try:
        conn.exec_driver_sql("PRAGMA query_only=ON;")
        yield conn
    finally:
        conn.close()

@pytest.fixture()
def ro_conn(engine):
    """A single read-only connection you can use inside a test."""
    with readonly_connection(engine) as conn:
        yield conn


# ------------------------------------------------------------------------------
# Clean logging / binds between tests
# ------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_between_tests():
    root = logging.getLogger()
    before = list(root.handlers)
    lvl = root.level
    with contextlib.suppress(Exception):
        db.session.rollback()
    with contextlib.suppress(Exception):
        db.session.bind = None
    yield
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
    root.setLevel(lvl)
    with contextlib.suppress(Exception):
        db.session.bind = None



# ------------------------------------------------------------------------------
# Small helpers & stable toggles
# ------------------------------------------------------------------------------

@pytest.fixture()
def customer_ids(app, db_session):
    return seed_minimal_customer()


@pytest.fixture(autouse=True, scope="session")
def policy_env():
    p = pathlib.Path("app/slices/governance/data/policy_issuance.json").resolve()
    os.environ["VCDB_POLICY_ISSUANCE"] = str(p)
    yield
    os.environ.pop("VCDB_POLICY_ISSUANCE", None)


@contextlib.contextmanager
def with_readonly_session():
    """
    Use a *temporary* scoped session bound to a fresh read-only SQLite connection.
    Restores the original db.session object after the block (even on error).
    """
    # 1) fresh connection + PRAGMAs
    conn = db.engine.connect()
    conn.exec_driver_sql("PRAGMA foreign_keys = ON;")


    # 2) new scoped session bound to this read-only connection
    RO_Session = scoped_session(
        sessionmaker(bind=conn, autoflush=False, expire_on_commit=False)
    )

    # 3) swap the *session object* (not just its bind)
    from typing import cast
    from flask_sqlalchemy import SQLAlchemy
    _db = cast(SQLAlchemy, db)
    old_session = _db.session
    _db.session = RO_Session  # type: ignore[assignment]
    try:
        yield
    finally:
        # Always clean up, even on exceptions
        with contextlib.suppress(Exception):
            db.session.rollback()
        with contextlib.suppress(Exception):
            _db.session.remove()      # type: ignore[call-arg]
        _db.session = old_session     # type: ignore[assignment]
        with contextlib.suppress(Exception):
            conn.close()


@pytest.fixture(autouse=True)
def reset_feature_flags(app):
    """Ensure feature flags are stable each test."""
    app.config.update({
        "CALENDAR_DEV_BLACKOUT_TRIPWIRE": False,
        "ALLOW_DEV_ASSUME_ROLES": True,
    })
    yield
