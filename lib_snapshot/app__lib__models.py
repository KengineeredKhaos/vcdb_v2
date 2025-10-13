# app/lib/models.py
from sqlalchemy import String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.lib.ids import new_ulid


class ULIDPK:
    ulid: Mapped[str] = mapped_column(
        String(26), primary_key=True, nullable=False
    )


def _assign_ulid(mapper, connection, target):
    if getattr(target, "ulid", None):
        return
    try:
        target.ulid = new_ulid()
    except Exception:
        # last-ditch fallback if necessary
        from app.lib.ids import new_ulid as _new

        target.ulid = _new()


def register_ulid_pk(model_cls):
    event.listen(model_cls, "before_insert", _assign_ulid)
    return model_cls
