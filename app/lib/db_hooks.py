# app/lib/db_hooks.py
from __future__ import annotations

import sqlite3
from contextlib import suppress

from sqlalchemy import event

from app.extensions import db


def install_sqlite_engine_hooks() -> None:
    """
    Engine-level pragmas that are safe for all test/app environments.
    - Enforce FK constraints (sqlite default is OFF)
    - Journal/WAL settings only if you want them globally (kept minimal here)
    """
    eng = db.engine

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        if isinstance(dbapi_conn, sqlite3.Connection):
            with suppress(Exception):
                dbapi_conn.execute("PRAGMA foreign_keys=ON;")
