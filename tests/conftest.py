from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from app.extensions import db
from app.lib.ids import new_ulid


def _remove_sqlite_files(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{db_path}{suffix}")
        try:
            p.unlink()
        except FileNotFoundError:
            pass


@pytest.fixture
def app() -> Flask:
    app = create_app("config.TestConfig")

    db_path = Path(app.instance_path) / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Start every test from a clean SQLite file set.
    _remove_sqlite_files(db_path)

    app.config.update(
        TESTING=True,
        PROPAGATE_EXCEPTIONS=True,
        SECRET_KEY="test-secret",
        WTF_CSRF_ENABLED=False,
        WTF_CSRF_CHECK_DEFAULT=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        DATABASE=str(db_path),
    )
    app.testing = True

    # Clear policy caches so policy edits are always seen in tests.
    try:
        from app.extensions import policies

        policies._CACHE.clear()  # type: ignore[attr-defined]
        policies._CATALOG = None  # type: ignore[attr-defined]
    except Exception:
        pass

    with app.app_context():
        from app.cli_seed import seed_bootstrap_impl

        seed_bootstrap_impl(
            fresh=True,
            force=True,
            faker_seed=1337,
            customers=2,
            resources=1,
            sponsors=1,
        )

    yield app

    with app.app_context():
        try:
            db.session.remove()
        except Exception:
            pass

        try:
            db.engine.dispose()
        except Exception:
            pass

    _remove_sqlite_files(db_path)


@pytest.fixture
def client(app: Flask):
    return app.test_client()


@pytest.fixture
def staff_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "staff"})
    return client


@pytest.fixture
def ulid() -> Callable[[], str]:
    def _make() -> str:
        return new_ulid()

    return _make
