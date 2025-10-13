# Generated scaffolding — VCDB v2 — 2025-09-22 00:11:24 UTC
from __future__ import annotations

from app.extensions import db
from app.lib.chrono import utc_now


"""Calendar slice models (MVP).
Keep business fields here; cross-cutting IDs/emitters live in app/extensions.
"""


class CalendarRecord(db.Model):
    __tablename__ = "calendar"
    id = db.Column(db.String(26), primary_key=True)  # ULID string
    status = db.Column(db.String(32), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # TODO: add slice-specific fields per Scaffolding Docs
