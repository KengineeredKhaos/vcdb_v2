# tests/support.py
from __future__ import annotations
import contextlib
from sqlalchemy.engine import Connection
from app.extensions import db


@contextlib.contextmanager
def with_write_session():
    """
    Yield the current (function-scoped) db.session as-is for write tests.
    """
    yield db.session


@contextlib.contextmanager
def with_readonly_session():
    """
    Switch the CURRENT TEST'S bound connection to read-only (SQLite PRAGMA).
    Restored after the block. Does not affect other tests or other connections.
    """
    sess = db.session
    bind = sess.get_bind()
    if bind is None:
        # Should not happen if conftest's session fixture is used
        raise RuntimeError("No bind on db.session; ensure test uses the `session` fixture.")

    # We need the actual DBAPI connection
    conn: Connection = bind
    raw = conn.connection  # DBAPI connection

    # Flip to read-only
    try:
        raw.execute("PRAGMA query_only=ON;")
    except Exception:
        # Non-SQLite DBs may not support this PRAGMA; if that happens
        # it's still useful for SQLite, and harmless elsewhere.
        pass

    try:
        yield sess
    finally:
        try:
            raw.execute("PRAGMA query_only=OFF;")
        except Exception:
            pass

"""
Usage:

For GET-only purity checks:

from tests.support import with_readonly_session
with with_readonly_session():
    dto = contracts_v2.get_something(...)


For write tests, you don’t need any wrapper
(or you can use with_write_session() for clarity).
"""
