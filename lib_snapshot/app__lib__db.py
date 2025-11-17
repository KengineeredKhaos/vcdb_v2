# app/lib/db.py
from contextlib import contextmanager
from typing import Iterator

from flask_sqlalchemy import SQLAlchemy


@contextmanager
def commit_or_rollback(db: SQLAlchemy) -> Iterator[None]:
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
