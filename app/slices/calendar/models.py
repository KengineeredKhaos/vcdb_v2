# app/slices/calendar/models.py
from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


class Calendar(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "calendar"

    # What/when
    kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="one_off"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planned"
    )
    event_title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="untitled"
    )
    location_txt: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    notes_txt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color_label: Mapped[str | None] = mapped_column(String(16), nullable=True)

    starts_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    ends_at_utc: Mapped[str | None] = mapped_column(String(30), nullable=True)
    all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Recurrence (optional)
    recurrence_rrule: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    recurrence_exdates_json: Mapped[dict | list | None] = mapped_column(
        JSON, nullable=True
    )

    # Links
    project_ulid: Mapped[str | None] = ULIDFK(
        "project_project", nullable=True, ondelete="SET NULL"
    )
    task_ulid: Mapped[str | None] = ULIDFK(
        "project_task", nullable=True, ondelete="SET NULL"
    )

    owner_ulid: Mapped[str | None] = ULIDFK(
        "entity_entity", nullable=True, ondelete="SET NULL"
    )
    assigned_to_ulid: Mapped[str | None] = ULIDFK(
        "entity_entity", nullable=True, ondelete="SET NULL"
    )

    # Visibility & alerts (optional)
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="internal"
    )
    reminder_minutes_before: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    reminders_json: Mapped[dict | list | None] = mapped_column(
        JSON, nullable=True
    )

    # Lifecycle
    done_at_utc: Mapped[str | None] = mapped_column(String(30), nullable=True)
    canceled_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    archived_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    archived_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # Tracing
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        # Time & status queries
        Index("ix_calendar_time_window", "starts_at_utc", "ends_at_utc"),
        Index("ix_calendar_status", "status"),
        # Ownership/assignment & lookups
        Index("ix_calendar_event", "event_title"),
        Index("ix_calendar_project", "project_ulid"),
        Index("ix_calendar_owner", "owner_ulid"),
        Index("ix_calendar_assignee", "assigned_to_ulid"),
        CheckConstraint(
            "(starts_at_utc IS NULL OR ends_at_utc IS NULL) "
            "OR (starts_at_utc <= ends_at_utc)",
            name="ck_calendar_time_window_valid",
        ),
    )


class Project(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "project_project"

    project_title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="untitled"
    )

    # Finance link (expects a finance_fund table/slice)
    fund_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # Ownership
    owner_ulid: Mapped[str | None] = ULIDFK(
        "entity_entity",
        nullable=True,
    )

    # Optional: phase/status for projects themselves
    phase_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="planned"
    )

    __table_args__ = (
        Index("ix_project_title", "project_title"),
        Index("ix_project_fund", "fund_ulid"),
        Index("ix_project_owner", "owner_ulid"),
        Index("ix_project_status", "status"),
    )


class Task(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "project_task"

    task_title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="untitled"
    )
    task_detail: Mapped[str | None] = mapped_column(
        String(254), nullable=True
    )

    # Belongs to a project
    project_ulid: Mapped[str | None] = ULIDFK(
        "project_project",
        nullable=False,
    )

    # Assignment
    assigned_to_ulid: Mapped[str | None] = ULIDFK(
        "entity_entity", nullable=True, ondelete="SET NULL"
    )

    # Scheduling (optional for tasks)
    due_at_utc: Mapped[str | None] = mapped_column(String(30), nullable=True)
    done_at_utc: Mapped[str | None] = mapped_column(String(30), nullable=True)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="open"
    )

    __table_args__ = (
        Index("ix_task_title", "task_title"),
        Index("ix_task_project", "project_ulid"),
        Index("ix_task_assignee", "assigned_to_ulid"),
        Index("ix_task_status", "status"),
    )
