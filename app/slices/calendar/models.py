# app/slices/calendar/models.py
"""
Project → Tasks → Budget Snapshot/Lines → Demand Draft →
FundingDemand

And each layer now owns one honest truth:

Task = work to be performed
BudgetLine = expected cost component
BudgetSnapshot = stable cost picture at a point in time
DemandDraft = pre-publish ask under Calendar/Governance review
FundingDemand = published execution-facing demand
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


class Calendar(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "calendar"

    # What/when
    kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="one_off"
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft"
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

    # DEPRECATED Finance link (legacy; will be retired later)
    fund_ulid: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # NEW
    # semantic key-> Governance policy: allowed fund archetypes-> Finance: COA
    # replaces fund_ulid with semantic policy key rather than a
    # direct finance slice reference.
    # funding constraints / reporting / allowed funding archetypes
    funding_profile_key: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )

    # Ownership
    owner_ulid: Mapped[str | None] = ULIDFK(
        "entity_entity",
        nullable=True,
        ondelete="SET NULL",
    )

    # Optional: phase/status for projects themselves
    phase_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="planned"
    )

    # New: convenience relationship to funding plans
    funding_plans: Mapped[list[ProjectFundingPlan]] = relationship(
        "ProjectFundingPlan",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    funding_demands: Mapped[list[FundingDemand]] = relationship(
        "FundingDemand",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    budget_snapshots: Mapped[list[ProjectBudgetSnapshot]] = relationship(
        "ProjectBudgetSnapshot",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    demand_drafts: Mapped[list[DemandDraft]] = relationship(
        "DemandDraft",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_project_title", "project_title"),
        Index("ix_project_fund", "fund_ulid"),
        Index("ix_project_owner", "owner_ulid"),
        Index("ix_project_status", "status"),
        Index("ix_project_funding_profile", "funding_profile_key"),
    )


class Task(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "project_task"

    # Belongs to a project (required)
    project_ulid: Mapped[str | None] = ULIDFK(
        "project_project",
        nullable=False,
    )

    # NEW: Task -> Project relationship
    project: Mapped[Project] = relationship(
        "Project",
        back_populates="tasks",
        passive_deletes=True,
    )

    task_title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="untitled"
    )

    task_detail: Mapped[str | None] = mapped_column(
        String(254), nullable=True
    )

    # Sematic token -> Governance policy -> Finance COA
    # This is an "expense routing" clue for Governance
    task_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Planning fields (use integers for math)
    estimate_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hours_est_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requirements_json: Mapped[dict | list | None] = mapped_column(
        JSON, nullable=True
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
    budget_lines: Mapped[list[ProjectBudgetLine]] = relationship(
        "ProjectBudgetLine",
        back_populates="task",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_task_title", "task_title"),
        Index("ix_task_project", "project_ulid"),
        Index("ix_task_assignee", "assigned_to_ulid"),
        Index("ix_task_status", "status"),
        Index("ix_task_kind", "task_kind"),
        CheckConstraint(
            "estimate_cents IS NULL OR estimate_cents >= 0",
            name="ck_task_estimate_nonneg",
        ),
        CheckConstraint(
            "hours_est_minutes IS NULL OR hours_est_minutes >= 0",
            name="ck_task_hours_nonneg",
        ),
    )


class ProjectFundingPlan(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "funding_plan"

    # Human-facing short label, similar to FundingProspect.label
    label: Mapped[str] = mapped_column(
        String(80), nullable=False, default="unnamed"
    )

    # Governance / reporting classifications
    source_kind: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # e.g. grant_reimbursement|matching_funds|internal_operations

    fund_archetype_key: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # e.g. grant_reimbursement|general_unrestricted

    # Planned amount (cents). Optional, but non-negative if present.
    expected_amount_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # True for in-kind; False/NULL for purely monetary
    is_in_kind: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Optional hint for who we expect this from (PII-free)
    expected_sponsor_hint: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )

    # Free-text notes about this funding line
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Optional relationship back to Project (handy in services)
    project_ulid: Mapped[str] = ULIDFK(
        "project_project",
        nullable=False,
        ondelete="CASCADE",  # or SET NULL if you want it nullable
    )

    # Link: each funding plan row belongs to a single Calendar Project.
    project: Mapped[Project] = relationship(
        "Project",
        back_populates="funding_plans",
        foreign_keys=[project_ulid],
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_funding_plan_project", "project_ulid"),
        Index("ix_funding_plan_source_kind", "source_kind"),
        Index("ix_funding_plan_archetype", "fund_archetype_key"),
        Index("ix_funding_plan_is_in_kind", "is_in_kind"),
        CheckConstraint(
            "expected_amount_cents IS NULL OR expected_amount_cents >= 0",
            name="ck_funding_plan_expected_nonneg",
        ),
    )


class FundingDemand(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "funding_demand"

    """
    DTO Example:

    FundingDemandDTO(
        funding_demand_ulid=row.ulid,
        project_ulid=row.project_ulid,
        title=row.title,
        status=row.status,
        goal_cents=row.goal_cents,
    )
    """
    project: Mapped[Project | None] = relationship(
        "Project",
        back_populates="funding_demands",
        passive_deletes=True,
    )

    project_ulid: Mapped[str | None] = ULIDFK(
        "project_project",
        nullable=True,
        ondelete="SET NULL",
    )

    # Title of the funding demand (NOT the project title)
    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="unnamed funding demand",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )

    goal_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    deadline_date: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    spending_class: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    eligible_fund_codes_json: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    tag_any_json: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    published_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    closed_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    published_context_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    origin_draft_ulid: Mapped[str | None] = ULIDFK(
        "demand_draft",
        nullable=True,
        ondelete="RESTRICT",
    )

    origin_draft: Mapped[DemandDraft | None] = relationship(
        "DemandDraft",
        back_populates="published_funding_demand",
        foreign_keys=[origin_draft_ulid],
    )

    __table_args__ = (
        CheckConstraint(
            "goal_cents >= 0", name="ck_funding_demand_goal_nonneg"
        ),
        Index("ix_funding_demand_project_status", "project_ulid", "status"),
        CheckConstraint(
            "status IN ('draft','published','funding_in_progress','funded','executing','closed')",
            name="ck_funding_demand_status",
        ),
        UniqueConstraint(
            "origin_draft_ulid",
            name="uq_funding_demand_origin_draft",
        ),
    )


class ProjectBudgetSnapshot(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "project_budget_snapshot"

    project_ulid: Mapped[str] = ULIDFK(
        "project_project",
        nullable=False,
        ondelete="CASCADE",
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="budget_snapshots",
        passive_deletes=True,
    )

    snapshot_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="working budget",
    )

    scope_summary: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    gross_cost_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    expected_offset_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    net_need_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    assumptions_note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    based_on_snapshot_ulid: Mapped[str | None] = ULIDFK(
        "project_budget_snapshot",
        nullable=True,
        ondelete="SET NULL",
    )

    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    locked_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    lines: Mapped[list[ProjectBudgetLine]] = relationship(
        "ProjectBudgetLine",
        back_populates="budget_snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    demand_drafts: Mapped[list[DemandDraft]] = relationship(
        "DemandDraft",
        back_populates="budget_snapshot",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(ulid) = 26",
            name="ck_budget_snapshot_ulid_len_26",
        ),
        CheckConstraint(
            "gross_cost_cents >= 0",
            name="ck_budget_snapshot_gross_nonneg",
        ),
        CheckConstraint(
            "expected_offset_cents >= 0",
            name="ck_budget_snapshot_offset_nonneg",
        ),
        CheckConstraint(
            "net_need_cents >= 0",
            name="ck_budget_snapshot_need_nonneg",
        ),
        CheckConstraint(
            "gross_cost_cents >= expected_offset_cents",
            name="ck_budget_snapshot_offset_le_gross",
        ),
        CheckConstraint(
            "net_need_cents = gross_cost_cents - expected_offset_cents",
            name="ck_budget_snapshot_net_matches_parts",
        ),
        Index(
            "ix_budget_snapshot_project",
            "project_ulid",
        ),
        Index(
            "ix_budget_snapshot_project_current",
            "project_ulid",
            "is_current",
        ),
        Index(
            "ix_budget_snapshot_project_locked",
            "project_ulid",
            "is_locked",
        ),
    )


class ProjectBudgetLine(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "project_budget_line"

    budget_snapshot_ulid: Mapped[str] = ULIDFK(
        "project_budget_snapshot",
        nullable=False,
        ondelete="CASCADE",
    )

    budget_snapshot: Mapped[ProjectBudgetSnapshot] = relationship(
        "ProjectBudgetSnapshot",
        back_populates="lines",
        passive_deletes=True,
    )

    task_ulid: Mapped[str | None] = ULIDFK(
        "project_task",
        nullable=True,
        ondelete="SET NULL",
    )

    task: Mapped[Task | None] = relationship(
        "Task",
        back_populates="budget_lines",
        passive_deletes=True,
    )

    line_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="materials",
    )

    label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="unnamed budget line",
    )

    detail: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    basis_qty: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    basis_unit: Mapped[str | None] = mapped_column(
        String(24),
        nullable=True,
    )

    unit_cost_cents: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    estimated_total_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    is_offset: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    offset_kind: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    copied_from_line_ulid: Mapped[str | None] = ULIDFK(
        "project_budget_line",
        nullable=True,
        ondelete="SET NULL",
    )

    __table_args__ = (
        CheckConstraint(
            "length(ulid) = 26",
            name="ck_budget_line_ulid_len_26",
        ),
        CheckConstraint(
            "basis_qty IS NULL OR basis_qty >= 0",
            name="ck_budget_line_qty_nonneg",
        ),
        CheckConstraint(
            "unit_cost_cents IS NULL OR unit_cost_cents >= 0",
            name="ck_budget_line_unit_cost_nonneg",
        ),
        CheckConstraint(
            "estimated_total_cents >= 0",
            name="ck_budget_line_total_nonneg",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_budget_line_sort_nonneg",
        ),
        CheckConstraint(
            "("
            "is_offset = 0 AND offset_kind IS NULL"
            ") OR ("
            "is_offset = 1 AND offset_kind IS NOT NULL"
            ")",
            name="ck_budget_line_offset_kind_consistent",
        ),
        Index(
            "ix_budget_line_snapshot",
            "budget_snapshot_ulid",
        ),
        Index(
            "ix_budget_line_task",
            "task_ulid",
        ),
        Index(
            "ix_budget_line_kind",
            "line_kind",
        ),
        Index(
            "ix_budget_line_snapshot_sort",
            "budget_snapshot_ulid",
            "sort_order",
        ),
    )


class DemandDraft(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "demand_draft"

    project_ulid: Mapped[str] = ULIDFK(
        "project_project",
        nullable=False,
        ondelete="CASCADE",
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="demand_drafts",
        passive_deletes=True,
    )

    budget_snapshot_ulid: Mapped[str] = ULIDFK(
        "project_budget_snapshot",
        nullable=False,
        ondelete="RESTRICT",
    )

    budget_snapshot: Mapped[ProjectBudgetSnapshot] = relationship(
        "ProjectBudgetSnapshot",
        back_populates="demand_drafts",
        passive_deletes=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="unnamed demand draft",
    )

    summary: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    scope_summary: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    requested_amount_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    deadline_date: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    spending_class_candidate: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    source_profile_key: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    ops_support_planned: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    tag_any_json: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    governance_note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    approved_semantics_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    ready_for_review_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    review_decided_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    approved_for_publish_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    promoted_at_utc: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    published_funding_demand: Mapped[FundingDemand | None] = relationship(
        "FundingDemand",
        back_populates="origin_draft",
        uselist=False,
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(ulid) = 26",
            name="ck_demand_draft_ulid_len_26",
        ),
        CheckConstraint(
            "requested_amount_cents >= 0",
            name="ck_demand_draft_amount_nonneg",
        ),
        CheckConstraint(
            "status IN ("
            "'draft',"
            "'ready_for_review',"
            "'governance_review_pending',"
            "'returned_for_revision',"
            "'approved_for_publish'"
            ")",
            name="ck_demand_draft_status",
        ),
        Index(
            "ix_demand_draft_project_status",
            "project_ulid",
            "status",
        ),
        Index(
            "ix_demand_draft_snapshot",
            "budget_snapshot_ulid",
        ),
    )


class ProjectTag(db.Model, ULIDPK):
    __tablename__ = "project_tag"

    project_ulid: Mapped[str] = ULIDFK(
        "project_project",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )

    tag_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
