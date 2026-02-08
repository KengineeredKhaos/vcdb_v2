# app/lib/db.py
from collections.abc import Iterator
from contextlib import contextmanager

from flask_sqlalchemy import SQLAlchemy


@contextmanager
def commit_or_rollback(db: SQLAlchemy) -> Iterator[None]:
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
