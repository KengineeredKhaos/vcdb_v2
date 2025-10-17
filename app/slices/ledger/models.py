# app/slices/ledger/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.chrono import utcnow_naive
from app.lib.models import ULIDPK


class LedgerEvent(db.Model, ULIDPK):
    __tablename__ = "ledger_event"

    type: Mapped[str] = mapped_column(
        String(64), index=True
    )  # e.g. "auth.login.success"
    happened_at_utc: Mapped[str | None] = mapped_column(
        String(30), default=utcnow_naive, index=True
    )

    actor_ulid: Mapped[str | None] = mapped_column(
        String(26), index=True, nullable=True
    )
    subject_ulid: Mapped[str | None] = mapped_column(
        String(26), index=True, nullable=True
    )
    entity_ulid: Mapped[str | None] = mapped_column(
        String(26), index=True, nullable=True
    )

    changed_fields: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )  # names only, never values
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # no PII

    request_id: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True
    )
    chain_key: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )

    prev_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary(32), nullable=True
    )
    hash: Mapped[bytes] = mapped_column(
        LargeBinary(32), nullable=False, index=True
    )
