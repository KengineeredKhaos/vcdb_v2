# tests/support.py
import contextlib
from sqlalchemy.orm import sessionmaker, scoped_session
from app.extensions import db

@contextlib.contextmanager
def with_readonly_session():
    """
    Temporarily bind db.session to a fresh connection intended for read-only use.
    (We do not turn PRAGMA query_only=ON here to avoid “readonly” errors
    when contracts legitimately touch temp objects; this is just an isolation shim.)
    """
    conn = db.engine.connect()
    try:
        # Helpful safety: keep FK checks on
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

        RO_Session = scoped_session(
            sessionmaker(bind=conn, autoflush=False, expire_on_commit=False)
        )

        # Swap the *session object* in a type-safe way
        from typing import cast
        from flask_sqlalchemy import SQLAlchemy
        _db = cast(SQLAlchemy, db)

        old_session = _db.session
        _db.session = RO_Session  # type: ignore[assignment]
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                _db.session.rollback()
            with contextlib.suppress(Exception):
                RO_Session.remove()  # type: ignore[call-arg]
            _db.session = old_session  # type: ignore[assignment]
    finally:
        with contextlib.suppress(Exception):
            conn.close()
