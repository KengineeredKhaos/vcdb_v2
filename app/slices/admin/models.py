# app/slices/admin/models.py

from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import ULIDPK


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


class AdminInboxItem(db.Model, ULIDPK):
    __tablename__ = "admin_inbox_item"

    source_slice: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source_ref_ulid: Mapped[str] = mapped_column(String(26), nullable=False)

    subject_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    source_status: Mapped[str] = mapped_column(String(64), nullable=False)
    # Source-owned statuses:
    # pending_review | awaiting_authorization | approved
    # rejected | cancelled | resolved

    admin_status: Mapped[str] = mapped_column(String(32), nullable=False)
    # admin_status:
    # Hot queue: open | acknowledged | in_review | snoozed
    # Terminal: resolved | source_closed | dismissed |duplicate

    workflow_key: Mapped[str] = mapped_column(String(128), nullable=False)
    resolution_route: Mapped[str] = mapped_column(String(200), nullable=False)

    context_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    opened_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)

    acknowledged_by_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    acknowledged_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    closed_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    close_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    dedupe_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )

    __table_args__ = (
        db.Index(
            "ix_admin_inbox_item_active",
            "admin_status",
            "severity",
            "updated_at_utc",
        ),
    )


class AdminInboxArchive(db.Model, ULIDPK):
    __tablename__ = "admin_inbox_archive"

    original_inbox_ulid: Mapped[str] = mapped_column(
        db.String(26), nullable=False, unique=True
    )

    source_slice: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source_ref_ulid: Mapped[str] = mapped_column(String(26), nullable=False)
    subject_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    source_status: Mapped[str] = mapped_column(String(64), nullable=False)
    # Source-owned statuses:
    # pending_review | awaiting_authorization | approved
    # rejected | cancelled | resolved

    admin_status: Mapped[str] = mapped_column(String(32), nullable=False)
    # admin_status:
    # Hot queue: open | acknowledged | in_review | snoozed
    # Terminal: resolved | source_closed | dismissed |duplicate

    workflow_key: Mapped[str] = mapped_column(String(128), nullable=False)
    resolution_route: Mapped[str] = mapped_column(String(200), nullable=False)

    context_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    opened_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)

    acknowledged_by_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    acknowledged_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    closed_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    close_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    archived_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    archive_reason: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        db.Index(
            "ix_admin_inbox_archive_archived_at",
            "archived_at_utc",
        ),
        db.Index(
            "ix_admin_inbox_archive_source",
            "source_slice",
            "issue_kind",
        ),
        db.Index(
            "ix_admin_inbox_source_ref_ulid",
            "source_ref_ulid",
        ),
    )
