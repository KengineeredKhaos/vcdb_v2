# app/slices/admin/mapper.py
"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SliceHealthCardDTO:
    slice_key: str
    label: str
    status: str
    summary: str
    attention_count: int
    launch_route: str


@dataclass(frozen=True)
class InboxSummaryDTO:
    total_open: int
    high_severity: int
    stale_count: int


@dataclass(frozen=True)
class InboxItemDTO:
    source_slice: str
    issue_kind: str
    severity: str
    summary: str
    opened_at_utc: str
    status: str
    resolution_route: str
    allowed_actions_summary: str
    context_preview: str


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
class PolicyHealthSummaryDTO:
    policy_count: int
    valid_count: int
    warning_count: int
    error_count: int
    last_checked_utc: str | None


@dataclass(frozen=True)
class AuthOperatorSummaryDTO:
    active_operator_count: int
    disabled_operator_count: int
    locked_operator_count: int
    attention_count: int


@dataclass(frozen=True)
class DashboardDTO:
    title: str
    summary: str
    inbox_summary: InboxSummaryDTO
    policy_summary: PolicyHealthSummaryDTO
    auth_summary: AuthOperatorSummaryDTO
    slice_cards: tuple[SliceHealthCardDTO, ...]
    recent_activity_summary: tuple[str, ...]


@dataclass(frozen=True)
class InboxPageDTO:
    title: str
    summary: str
    inbox_summary: InboxSummaryDTO
    items: tuple[InboxItemDTO, ...]
    status_legend: tuple[str, ...] = (
        "open",
        "in_review",
        "dismissed",
        "escalated",
    )


@dataclass(frozen=True)
class CronPageDTO:
    title: str
    summary: str
    jobs: tuple[CronJobStatusDTO, ...]


@dataclass(frozen=True)
class PolicyIndexPageDTO:
    title: str
    summary: str
    health: PolicyHealthSummaryDTO
    items: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class AuthOperatorsPageDTO:
    title: str
    summary: str
    auth_summary: AuthOperatorSummaryDTO
    items: tuple[dict[str, str], ...]


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


def to_inbox_summary(
    *,
    total_open: int,
    high_severity: int,
    stale_count: int,
) -> InboxSummaryDTO:
    return InboxSummaryDTO(
        total_open=int(total_open),
        high_severity=int(high_severity),
        stale_count=int(stale_count),
    )


def to_inbox_item(
    *,
    source_slice: str,
    issue_kind: str,
    severity: str,
    summary: str,
    opened_at_utc: str,
    status: str,
    resolution_route: str,
    allowed_actions_summary: str,
    context_preview: str,
) -> InboxItemDTO:
    return InboxItemDTO(
        source_slice=source_slice,
        issue_kind=issue_kind,
        severity=severity,
        summary=summary,
        opened_at_utc=opened_at_utc,
        status=status,
        resolution_route=resolution_route,
        allowed_actions_summary=allowed_actions_summary,
        context_preview=context_preview,
    )


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


def to_dashboard(
    *,
    title: str,
    summary: str,
    inbox_summary: InboxSummaryDTO,
    policy_summary: PolicyHealthSummaryDTO,
    auth_summary: AuthOperatorSummaryDTO,
    slice_cards: tuple[SliceHealthCardDTO, ...],
    recent_activity_summary: tuple[str, ...],
) -> DashboardDTO:
    return DashboardDTO(
        title=title,
        summary=summary,
        inbox_summary=inbox_summary,
        policy_summary=policy_summary,
        auth_summary=auth_summary,
        slice_cards=slice_cards,
        recent_activity_summary=recent_activity_summary,
    )


def to_inbox_page(
    *,
    title: str,
    summary: str,
    inbox_summary: InboxSummaryDTO,
    items: tuple[InboxItemDTO, ...],
) -> InboxPageDTO:
    return InboxPageDTO(
        title=title,
        summary=summary,
        inbox_summary=inbox_summary,
        items=items,
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


def to_policy_index_page(
    *,
    title: str,
    summary: str,
    health: PolicyHealthSummaryDTO,
    items: tuple[dict[str, str], ...],
) -> PolicyIndexPageDTO:
    return PolicyIndexPageDTO(
        title=title,
        summary=summary,
        health=health,
        items=items,
    )


def to_auth_operators_page(
    *,
    title: str,
    summary: str,
    auth_summary: AuthOperatorSummaryDTO,
    items: tuple[dict[str, str], ...],
) -> AuthOperatorsPageDTO:
    return AuthOperatorsPageDTO(
        title=title,
        summary=summary,
        auth_summary=auth_summary,
        items=items,
    )
