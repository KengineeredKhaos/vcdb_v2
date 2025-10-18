# conftest.py (repo root)
import os
import pytest
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    os.environ["FLASK_ENV"] = "testing"
    app = create_app("config.TestConfig")
    with app.app_context():
        # Real schema
        from flask_migrate import upgrade

        upgrade()
        # Real seeds (the ones you already trust)
        from scripts.seed_governance import run as seed_gov
        from scripts.seed_auth import run as seed_auth
        from scripts.seed_calendar import run as seed_cal

        seed_gov()
        seed_auth()
        seed_cal()
        yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db
