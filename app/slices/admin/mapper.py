# app/slices/admin/mapper.py
"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# -----------------
# Dashboard
# -----------------


@dataclass(frozen=True)
class DashboardDTO:
    title: str
    summary: str
    inbox_summary: InboxSummaryDTO
    policy_summary: PolicyHealthSummaryDTO
    auth_summary: AuthOperatorSummaryDTO
    ledger_summary: LedgerDashboardSummaryDTO
    slice_cards: tuple[SliceHealthCardDTO, ...]
    recent_activity_summary: tuple[str, ...]


def to_dashboard(
    *,
    title: str,
    summary: str,
    inbox_summary: InboxSummaryDTO,
    policy_summary: PolicyHealthSummaryDTO,
    auth_summary: AuthOperatorSummaryDTO,
    ledger_summary: LedgerDashboardSummaryDTO,
    slice_cards: tuple[SliceHealthCardDTO, ...],
    recent_activity_summary: tuple[str, ...],
) -> DashboardDTO:
    return DashboardDTO(
        title=title,
        summary=summary,
        inbox_summary=inbox_summary,
        policy_summary=policy_summary,
        auth_summary=auth_summary,
        ledger_summary=ledger_summary,
        slice_cards=slice_cards,
        recent_activity_summary=recent_activity_summary,
    )


# -----------------
# Slice Health
# -----------------


@dataclass(frozen=True)
class SliceHealthCardDTO:
    slice_key: str
    label: str
    status: str
    summary: str
    attention_count: int
    launch_route: str


def to_slice_health_card(
    *,
    slice_key: str,
    label: str,
    status: str,
    summary: str,
    attention_count: int,
    launch_route: str,
) -> SliceHealthCardDTO:
    return SliceHealthCardDTO(
        slice_key=slice_key,
        label=label,
        status=status,
        summary=summary,
        attention_count=int(attention_count),
        launch_route=launch_route,
    )


@dataclass(frozen=True)
class LedgerDashboardSummaryDTO:
    has_gate_record: bool
    gate_reason_code: str | None
    gate_source_status: str | None
    routine_backup_allowed: bool
    dirty_forensic_backup_only: bool
    open_issue_count: int
    failed_open_issue_count: int
    anomaly_open_issue_count: int
    last_check_at_utc: str | None
    last_repair_at_utc: str | None
    launch_route: str


def to_ledger_dashboard_summary(
    *,
    has_gate_record: bool,
    gate_reason_code: str | None,
    gate_source_status: str | None,
    routine_backup_allowed: bool,
    dirty_forensic_backup_only: bool,
    open_issue_count: int,
    failed_open_issue_count: int,
    anomaly_open_issue_count: int,
    last_check_at_utc: str | None,
    last_repair_at_utc: str | None,
    launch_route: str,
) -> LedgerDashboardSummaryDTO:
    return LedgerDashboardSummaryDTO(
        has_gate_record=bool(has_gate_record),
        gate_reason_code=gate_reason_code,
        gate_source_status=gate_source_status,
        routine_backup_allowed=bool(routine_backup_allowed),
        dirty_forensic_backup_only=bool(dirty_forensic_backup_only),
        open_issue_count=int(open_issue_count),
        failed_open_issue_count=int(failed_open_issue_count),
        anomaly_open_issue_count=int(anomaly_open_issue_count),
        last_check_at_utc=last_check_at_utc,
        last_repair_at_utc=last_repair_at_utc,
        launch_route=launch_route,
    )


# -----------------
# Operators
# -----------------


@dataclass(frozen=True)
class AuthOperatorSummaryDTO:
    active_operator_count: int
    disabled_operator_count: int
    locked_operator_count: int
    attention_count: int


@dataclass(frozen=True)
class AuthOperatorsPageDTO:
    title: str
    summary: str
    auth_summary: AuthOperatorSummaryDTO
    items: tuple[dict[str, object], ...]


def to_auth_operator_summary(
    *,
    active_operator_count: int,
    disabled_operator_count: int,
    locked_operator_count: int,
    attention_count: int,
) -> AuthOperatorSummaryDTO:
    return AuthOperatorSummaryDTO(
        active_operator_count=int(active_operator_count),
        disabled_operator_count=int(disabled_operator_count),
        locked_operator_count=int(locked_operator_count),
        attention_count=int(attention_count),
    )


def to_auth_operators_page(
    *,
    title: str,
    summary: str,
    auth_summary: AuthOperatorSummaryDTO,
    items: tuple[dict[str, object], ...],
) -> AuthOperatorsPageDTO:
    return AuthOperatorsPageDTO(
        title=title,
        summary=summary,
        auth_summary=auth_summary,
        items=items,
    )


# -----------------
# Admin Inbox bits
# -----------------


@dataclass(frozen=True)
class InboxSummaryDTO:
    total_open: int
    failed_count: int
    stale_count: int


@dataclass(frozen=True)
class InboxItemDTO:
    alert_ulid: str
    source_slice: str
    reason_code: str
    alert_family: str
    summary: str
    opened_at_utc: str
    status: str
    launch_label: str
    launch_href: str | None
    allowed_actions_summary: str
    context_preview: str
    can_acknowledge: bool
    can_start_review: bool
    can_snooze: bool
    can_dismiss: bool
    can_mark_duplicate: bool


@dataclass(frozen=True)
class InboxPageDTO:
    title: str
    summary: str
    inbox_summary: InboxSummaryDTO
    current_view: str
    items: tuple[InboxItemDTO, ...]
    status_legend: tuple[str, ...] = (
        "open",
        "acknowledged",
        "in_review",
        "snoozed",
    )


def to_inbox_summary(
    *,
    total_open: int,
    failed_count: int,
    stale_count: int,
) -> InboxSummaryDTO:
    return InboxSummaryDTO(
        total_open=int(total_open),
        failed_count=int(failed_count),
        stale_count=int(stale_count),
    )


def to_inbox_item(
    *,
    alert_ulid: str,
    source_slice: str,
    reason_code: str,
    alert_family: str,
    summary: str,
    opened_at_utc: str,
    status: str,
    launch_label: str,
    launch_href: str | None,
    allowed_actions_summary: str,
    context_preview: str,
    can_acknowledge: bool,
    can_start_review: bool,
    can_snooze: bool,
    can_dismiss: bool,
    can_mark_duplicate: bool,
) -> InboxItemDTO:
    return InboxItemDTO(
        alert_ulid=alert_ulid,
        source_slice=source_slice,
        reason_code=reason_code,
        alert_family=alert_family,
        summary=summary,
        opened_at_utc=opened_at_utc,
        status=status,
        launch_label=launch_label,
        launch_href=launch_href,
        allowed_actions_summary=allowed_actions_summary,
        context_preview=context_preview,
        can_acknowledge=bool(can_acknowledge),
        can_start_review=bool(can_start_review),
        can_snooze=bool(can_snooze),
        can_dismiss=bool(can_dismiss),
        can_mark_duplicate=bool(can_mark_duplicate),
    )


def to_inbox_page(
    *,
    title: str,
    summary: str,
    inbox_summary: InboxSummaryDTO,
    current_view: str,
    items: tuple[InboxItemDTO, ...],
) -> InboxPageDTO:
    return InboxPageDTO(
        title=title,
        summary=summary,
        inbox_summary=inbox_summary,
        current_view=current_view,
        items=items,
    )


# -----------------
# Cron bits
# -----------------


@dataclass(frozen=True)
class CronJobStatusDTO:
    job_key: str
    label: str
    status: str
    last_success_utc: str | None
    last_failure_utc: str | None
    stale: bool
    note: str


@dataclass(frozen=True)
class CronPageDTO:
    title: str
    summary: str
    jobs: tuple[CronJobStatusDTO, ...]


def to_cron_job_status(
    *,
    job_key: str,
    label: str,
    status: str,
    last_success_utc: str | None,
    last_failure_utc: str | None,
    stale: bool,
    note: str,
) -> CronJobStatusDTO:
    return CronJobStatusDTO(
        job_key=job_key,
        label=label,
        status=status,
        last_success_utc=last_success_utc,
        last_failure_utc=last_failure_utc,
        stale=bool(stale),
        note=note,
    )


def to_cron_page(
    *,
    title: str,
    summary: str,
    jobs: tuple[CronJobStatusDTO, ...],
) -> CronPageDTO:
    return CronPageDTO(
        title=title,
        summary=summary,
        jobs=jobs,
    )


# -----------------
# Policy Bits
# -----------------


@dataclass(frozen=True)
class PolicyHealthSummaryDTO:
    policy_count: int
    valid_count: int
    warning_count: int
    error_count: int
    last_checked_utc: str | None


@dataclass(frozen=True)
class PolicyIssueDTO:
    source: str
    severity: str
    path: str
    message: str


@dataclass(frozen=True)
class PolicyIndexItemDTO:
    key: str
    title: str
    status: str
    version: str
    focus: str
    schema_state: str
    semantic_state: str
    issue_count: int
    review_route: str


@dataclass(frozen=True)
class PolicyMetaItemDTO:
    key: str
    value: str


@dataclass(frozen=True)
class PolicyDetailPageDTO:
    title: str
    summary: str
    policy_key: str
    current_hash: str
    current_text: str
    meta_items: tuple[PolicyMetaItemDTO, ...]
    issues: tuple[PolicyIssueDTO, ...]
    has_schema: bool
    schema_ok: bool
    semantic_ok: bool
    preview_route: str


@dataclass(frozen=True)
class PolicyPreviewPageDTO:
    title: str
    summary: str
    policy_key: str
    current_hash: str
    proposed_hash: str
    normalized_text: str
    diff_lines: tuple[str, ...]
    issues: tuple[PolicyIssueDTO, ...]
    change_summary: tuple[str, ...]
    commit_allowed: bool
    commit_route: str
    detail_route: str


@dataclass(frozen=True)
class PolicyIndexPageDTO:
    title: str
    summary: str
    health: PolicyHealthSummaryDTO
    items: tuple[PolicyIndexItemDTO, ...]


def to_policy_health_summary(
    *,
    policy_count: int,
    valid_count: int,
    warning_count: int,
    error_count: int,
    last_checked_utc: str | None,
) -> PolicyHealthSummaryDTO:
    return PolicyHealthSummaryDTO(
        policy_count=int(policy_count),
        valid_count=int(valid_count),
        warning_count=int(warning_count),
        error_count=int(error_count),
        last_checked_utc=last_checked_utc,
    )


def to_policy_issue(
    *,
    source: str,
    severity: str,
    path: str,
    message: str,
) -> PolicyIssueDTO:
    return PolicyIssueDTO(
        source=source,
        severity=severity,
        path=path,
        message=message,
    )


def to_policy_index_item(
    *,
    key: str,
    title: str,
    status: str,
    version: str,
    focus: str,
    schema_state: str,
    semantic_state: str,
    issue_count: int,
    review_route: str,
) -> PolicyIndexItemDTO:
    return PolicyIndexItemDTO(
        key=key,
        title=title,
        status=status,
        version=version,
        focus=focus,
        schema_state=schema_state,
        semantic_state=semantic_state,
        issue_count=int(issue_count),
        review_route=review_route,
    )


def to_policy_meta_item(*, key: str, value: str) -> PolicyMetaItemDTO:
    return PolicyMetaItemDTO(key=key, value=value)


def to_policy_detail_page(
    *,
    title: str,
    summary: str,
    policy_key: str,
    current_hash: str,
    current_text: str,
    meta_items: tuple[PolicyMetaItemDTO, ...],
    issues: tuple[PolicyIssueDTO, ...],
    has_schema: bool,
    schema_ok: bool,
    semantic_ok: bool,
    preview_route: str,
) -> PolicyDetailPageDTO:
    return PolicyDetailPageDTO(
        title=title,
        summary=summary,
        policy_key=policy_key,
        current_hash=current_hash,
        current_text=current_text,
        meta_items=meta_items,
        issues=issues,
        has_schema=bool(has_schema),
        schema_ok=bool(schema_ok),
        semantic_ok=bool(semantic_ok),
        preview_route=preview_route,
    )


def to_policy_preview_page(
    *,
    title: str,
    summary: str,
    policy_key: str,
    current_hash: str,
    proposed_hash: str,
    normalized_text: str,
    diff_lines: tuple[str, ...],
    issues: tuple[PolicyIssueDTO, ...],
    change_summary: tuple[str, ...],
    commit_allowed: bool,
    commit_route: str,
    detail_route: str,
) -> PolicyPreviewPageDTO:
    return PolicyPreviewPageDTO(
        title=title,
        summary=summary,
        policy_key=policy_key,
        current_hash=current_hash,
        proposed_hash=proposed_hash,
        normalized_text=normalized_text,
        diff_lines=diff_lines,
        issues=issues,
        change_summary=change_summary,
        commit_allowed=bool(commit_allowed),
        commit_route=commit_route,
        detail_route=detail_route,
    )


def to_policy_index_page(
    *,
    title: str,
    summary: str,
    health: PolicyHealthSummaryDTO,
    items: tuple[PolicyIndexItemDTO, ...],
) -> PolicyIndexPageDTO:
    return PolicyIndexPageDTO(
        title=title,
        summary=summary,
        health=health,
        items=items,
    )
