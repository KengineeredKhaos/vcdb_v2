# app/slices/admin/services.py
"""
VCDB v2 — Admin slice services

Read-side composition only for the Admin control surface foundation pass.
No commits, no rollbacks, no Ledger emits, no foreign write semantics.
"""

from __future__ import annotations

from .mapper import (
    AuthOperatorsPageDTO,
    CronPageDTO,
    DashboardDTO,
    InboxPageDTO,
    PolicyIndexPageDTO,
    to_auth_operator_summary,
    to_auth_operators_page,
    to_cron_job_status,
    to_cron_page,
    to_dashboard,
    to_inbox_item,
    to_inbox_page,
    to_inbox_summary,
    to_policy_health_summary,
    to_policy_index_page,
    to_slice_health_card,
)


def get_dashboard() -> DashboardDTO:
    inbox_summary = to_inbox_summary(
        total_open=0,
        high_severity=0,
        stale_count=0,
    )
    policy_summary = to_policy_health_summary(
        policy_count=0,
        valid_count=0,
        warning_count=0,
        error_count=0,
        last_checked_utc=None,
    )
    auth_summary = to_auth_operator_summary(
        active_operator_count=0,
        disabled_operator_count=0,
        locked_operator_count=0,
        attention_count=0,
    )
    slice_cards = (
        to_slice_health_card(
            slice_key="admin_inbox",
            label="Inbox",
            status="scaffold",
            summary="Unified Admin triage surface scaffolded.",
            attention_count=0,
            launch_route="admin.inbox",
        ),
        to_slice_health_card(
            slice_key="admin_cron",
            label="Cron",
            status="scaffold",
            summary="Cron supervision surface scaffolded.",
            attention_count=0,
            launch_route="admin.cron",
        ),
        to_slice_health_card(
            slice_key="admin_policy",
            label="Policy",
            status="scaffold",
            summary="Policy workflow surface scaffolded.",
            attention_count=0,
            launch_route="admin.policy_index",
        ),
        to_slice_health_card(
            slice_key="admin_auth",
            label="Auth",
            status="scaffold",
            summary="Auth operator management surface scaffolded.",
            attention_count=0,
            launch_route="admin.auth_operators",
        ),
    )
    recent_activity_summary = (
        "Admin control surface scaffold is live.",
        "Routes and page shells are landing cleanly.",
    )
    return to_dashboard(
        title="Admin Control Surface",
        summary=(
            "Observe system state, triage issues, supervise operations, "
            "and launch owning-slice workflows."
        ),
        inbox_summary=inbox_summary,
        policy_summary=policy_summary,
        auth_summary=auth_summary,
        slice_cards=slice_cards,
        recent_activity_summary=recent_activity_summary,
    )


def get_inbox_page() -> InboxPageDTO:
    inbox_summary = to_inbox_summary(
        total_open=0,
        high_severity=0,
        stale_count=0,
    )
    items = (
        to_inbox_item(
            source_slice="admin",
            issue_kind="scaffold_status",
            severity="info",
            summary="Unified inbox shell is live with no real issue feeds yet.",
            opened_at_utc="",
            status="open",
            resolution_route="admin.inbox",
            allowed_actions_summary="No action yet.",
            context_preview="Wave 1 scaffold placeholder.",
        ),
    )
    return to_inbox_page(
        title="Unified Admin Inbox",
        summary=(
            "Admin triage surface for slice-owned review items with real "
            "resolution paths."
        ),
        inbox_summary=inbox_summary,
        items=items,
    )


def get_cron_page() -> CronPageDTO:
    jobs = (
        to_cron_job_status(
            job_key="scaffold",
            label="Cron supervision scaffold",
            status="not_configured",
            last_success_utc=None,
            last_failure_utc=None,
            stale=False,
            note="CronStatus model exists, but live job wiring is deferred.",
        ),
    )
    return to_cron_page(
        title="Cron and Maintenance Supervision",
        summary=(
            "Supervise recurring jobs, failures, stale runs, and "
            "maintenance status."
        ),
        jobs=jobs,
    )


def get_policy_index_page() -> PolicyIndexPageDTO:
    health = to_policy_health_summary(
        policy_count=0,
        valid_count=0,
        warning_count=0,
        error_count=0,
        last_checked_utc=None,
    )
    items = (
        {
            "key": "scaffold",
            "label": "Policy workflow scaffold",
            "status": "not_connected",
        },
    )
    return to_policy_index_page(
        title="Policy Workflow Surface",
        summary=(
            "Admin frames the workflow. Governance owns policy meaning, "
            "validation, persistence, and audit semantics."
        ),
        health=health,
        items=items,
    )


def get_auth_operators_page() -> AuthOperatorsPageDTO:
    auth_summary = to_auth_operator_summary(
        active_operator_count=0,
        disabled_operator_count=0,
        locked_operator_count=0,
        attention_count=0,
    )
    items = (
        {
            "key": "scaffold",
            "label": "Auth operator surface scaffold",
            "status": "not_connected",
        },
    )
    return to_auth_operators_page(
        title="Auth Operator Management",
        summary=(
            "Admin surfaces operator state and launch points. Auth owns "
            "command semantics."
        ),
        auth_summary=auth_summary,
        items=items,
    )
