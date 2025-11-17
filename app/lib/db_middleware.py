# app/lib/db_middleware.py
"""
SQLite/SQLAlchemy request guardrails:

- GET/HEAD/OPTIONS run in read-only mode (SQLite: PRAGMA query_only=ON)
- Mutating verbs (POST/PUT/PATCH/DELETE) are writable
- On success: mutating verbs commit; safe verbs rollback
- On errors: always rollback
- Always remove the session
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from flask import g, request

from app.extensions import db


def _flip_query_only(on: bool) -> None:
    """Flip PRAGMA query_only for the *current* bound SQLite connection."""
    # Ensure a connection is bound (lazy until first use)
    if not db.session.is_active:
        db.session.connection()
    conn = db.session.get_bind()
    raw = conn.connection
    if isinstance(raw, sqlite3.Connection):
        try:
            raw.execute(f"PRAGMA query_only={'ON' if on else 'OFF'};")
        except Exception:
            pass

def init_request_db_guards(app) -> None:
    @app.before_request
    def _begin_request():
        g._vcdb_writable = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if not g._vcdb_writable:
            _flip_query_only(True)

    @app.after_request
    def _end_request(resp):
        try:
            if g.get("_vcdb_writable"):
                if 200 <= resp.status_code < 400:
                    db.session.commit()
                else:
                    db.session.rollback()
            else:
                db.session.rollback()
        finally:
            # Restore writable for pooled connection reuse
            if not g.get("_vcdb_writable"):
                _flip_query_only(False)
        return resp

    @app.teardown_request
    def _teardown_request(exc: Optional[BaseException]):
        if exc is not None:
            try:
                db.session.rollback()
            except Exception:
                pass
        try:
            db.session.remove()
        except Exception:
            pass
