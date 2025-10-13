# app/slices/admin/models.py
from __future__ import annotations
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.extensions import db


class CronStatus(db.Model):
    __tablename__ = "admin_cron_status"  # namespaced

    # Natural PK is fine here
    job_name: Mapped[str] = mapped_column(String(120), primary_key=True)

    # Store ISO-8601 Z strings for consistency with the rest of the app
    last_success_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_error_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:
        ok = bool(self.last_success_utc) and not self.last_error
        return f"<CronStatus {self.job_name} ok={ok}>"
