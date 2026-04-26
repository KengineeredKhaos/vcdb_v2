# app/slices/admin/models.py

from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import ULIDPK, IsoTimestamps


class CronStatus(db.Model):
    __tablename__ = "admin_cron_status"

    job_name: Mapped[str] = mapped_column(String(120), primary_key=True)

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


class AdminAlert(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "admin_alert"

    source_slice: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)

    target_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    source_status: Mapped[str] = mapped_column(String(64), nullable=False)
    admin_status: Mapped[str] = mapped_column(String(32), nullable=False)

    workflow_key: Mapped[str] = mapped_column(String(128), nullable=False)

    resolution_target_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    context_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    acknowledged_by_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    acknowledged_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    triaged_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    triaged_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    snoozed_until_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    duplicate_of_alert_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    triage_note: Mapped[str | None] = mapped_column(Text, nullable=True)

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
            "ix_admin_alert_active",
            "admin_status",
            "updated_at_utc",
        ),
        db.Index(
            "ix_admin_alert_request_reason",
            "request_id",
            "reason_code",
        ),
        db.Index(
            "ix_admin_alert_target_reason",
            "target_ulid",
            "reason_code",
        ),
    )


class AdminAlertArchive(db.Model, ULIDPK):
    __tablename__ = "admin_alert_archive"

    original_alert_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, unique=True
    )

    source_slice: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)

    target_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    source_status: Mapped[str] = mapped_column(String(64), nullable=False)
    admin_status: Mapped[str] = mapped_column(String(32), nullable=False)

    workflow_key: Mapped[str] = mapped_column(String(128), nullable=False)

    resolution_target_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    context_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    created_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)

    acknowledged_by_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    acknowledged_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    triaged_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    triaged_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    snoozed_until_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    duplicate_of_alert_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    triage_note: Mapped[str | None] = mapped_column(Text, nullable=True)

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
            "ix_admin_alert_archive_archived_at",
            "archived_at_utc",
        ),
        db.Index(
            "ix_admin_alert_archive_source_reason",
            "source_slice",
            "reason_code",
        ),
        db.Index(
            "ix_admin_alert_archive_request_id",
            "request_id",
        ),
    )


class CronRun(db.Model, ULIDPK):
    __tablename__ = "admin_cron_run"

    job_key: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    finished_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)
    trigger_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    host_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "job_key",
            "unit_key",
            "attempt_no",
            name="uq_admin_cron_run_job_unit_attempt",
        ),
        db.Index(
            "ix_admin_cron_run_job_started",
            "job_key",
            "started_at_utc",
        ),
        db.Index(
            "ix_admin_cron_run_status_started",
            "status",
            "started_at_utc",
        ),
    )


class CronLock(db.Model):
    __tablename__ = "admin_cron_lock"

    lock_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    job_key: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_key: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_run_ulid: Mapped[str] = mapped_column(String(26), nullable=False)
    acquired_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        db.Index(
            "ix_admin_cron_lock_job_unit",
            "job_key",
            "unit_key",
        ),
    )
