# app/slices/ledger/models.py
from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import ULIDPK


class LedgerEvent(db.Model, ULIDPK):
    __tablename__ = "ledger_event"
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, index=True
    )
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    principal_ulid: Mapped[str] = mapped_column(String(26))  # who acted
    subject_ulid: Mapped[str | None] = mapped_column(String(26))
    payload_json: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), index=True)
