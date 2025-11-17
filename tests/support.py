# tests/support.py
from __future__ import annotations

import contextlib

from app.extensions import db


@contextlib.contextmanager
def with_readonly_session():
    """
    Open a dedicated SQLAlchemy connection in SQLite read-only (query_only) mode,
    then bind a fresh session to it for the duration of the block.

    Usage:
        from tests.support import with_readonly_session
        with with_readonly_session():
            # call GET-only contracts here
            ...
    """
    conn = db.engine.connect()
    # SQLite: forbid writes on this connection
    conn.exec_driver_sql("PRAGMA query_only = ON;")
    trans = conn.begin()
    bind_before = db.session.get_bind()
    try:
        db.session.bind = conn  # temporarily bind session to this read-only connection
        yield
    finally:
        db.session.bind = bind_before
        try:
            trans.rollback()
        finally:
            conn.close()
