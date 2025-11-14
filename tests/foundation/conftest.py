# tests/foundation/conftest.py
import pytest
import os, pathlib
from app import create_app
from app.lib.chrono import utcnow_naive

@pytest.fixture(scope="session")
def app():
    # Use TestConfig + file-backed DB at app/instance/test.db
    os.environ.setdefault("VCDB_ENV", "testing")
    inst = pathlib.Path("app/instance"); inst.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SQLALCHEMY_DATABASE_URI", f"sqlite:///{inst/'test.db'}")
    return create_app("config.TestConfig")

@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.fixture()
def ro_session(app):
    # Expose a read-only session for GET-contract assertions.
    # If you have a proper read-only engine, wire it here; otherwise
    # use the main session but enforce no writes by rolling back at end.
    from app.extensions import db
    s = db.session()
    try:
        yield s
    finally:
        s.rollback()

@pytest.fixture()
def write_session(app):
    from app.extensions import db
    s = db.session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
