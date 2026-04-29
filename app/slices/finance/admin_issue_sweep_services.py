# app/slices/finance/admin_issue_sweep_services.py

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.finance import admin_issue_services as issue_svc
from app.slices.finance import quarantine_services as quarantine_svc
from app.slices.finance.models import FinanceSweepRun
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    CONTROL_STATE_DRIFT_REASON,
    JOURNAL_INTEGRITY_REASON,
    OPS_FLOAT_SANITY_REASON,
    POSTING_FACT_DRIFT_REASON,
    FinanceIssueScope,
    balance_projection_drift_scan,
    control_state_drift_scan,
    infer_balance_projection_scope,
    infer_control_state_scope,
    infer_journal_integrity_scope,
    infer_ops_float_scope,
    infer_posting_fact_scope,
    journal_integrity_scan,
    ops_float_sanity_scan,
    posting_fact_drift_scan,
)


@dataclass(frozen=True)
class FinanceSweepOutcome:
    """One scanner outcome from a Finance integrity sweep."""

    scan_key: str
    reason_code: str
    ok: bool
    finding_count: int
    issue_ulid: str | None
    quarantine_ulid: str | None
    message: str


@dataclass(frozen=True)
class FinanceSweepRunView:
    sweep_run_ulid: str
    request_id: str
    actor_ulid: str | None
    ran_at_utc: str
    scans_run: int
    clean_count: int
    dirty_count: int
    issue_count: int
    quarantine_count: int
    summary: dict[str, Any]


@dataclass(frozen=True)
class FinanceIntegritySweepResult:
    """PII-free summary of one Finance integrity sweep."""

    request_id: str
    scans_run: int
    clean_count: int
    dirty_count: int
    issue_ulids: tuple[str, ...]
    quarantine_ulids: tuple[str, ...]
    outcomes: tuple[FinanceSweepOutcome, ...]
    sweep_run_ulid: str | None = None


@dataclass(frozen=True)
class _SweepSpec:
    scan_key: str
    workflow_key: str
    dedupe_scope: str
    reason_code: str
    title: str
    dirty_message: str
    scanner: Callable[[], object]
    raiser: Callable[..., issue_svc.FinanceAdminIssueView]
    scope_inferer: Callable[[object], FinanceIssueScope]
    blocked_sentence: str



def _to_sweep_run_view(row: FinanceSweepRun) -> FinanceSweepRunView:
    return FinanceSweepRunView(
        sweep_run_ulid=row.ulid,
        request_id=row.request_id,
        actor_ulid=row.actor_ulid,
        ran_at_utc=row.ran_at_utc,
        scans_run=int(row.scans_run or 0),
        clean_count=int(row.clean_count or 0),
        dirty_count=int(row.dirty_count or 0),
        issue_count=int(row.issue_count or 0),
        quarantine_count=int(row.quarantine_count or 0),
        summary=dict(row.summary_json or {}),
    )


def _finding_count(scan_result: object) -> int:
    return int(getattr(scan_result, "finding_count", 0) or 0)


def _scan_ok(scan_result: object) -> bool:
    return bool(getattr(scan_result, "ok", False))


def _issue_notes(scan_result: object) -> dict[str, Any]:
    return {
        "reason_code": str(getattr(scan_result, "reason_code", "")),
        "source_status": str(getattr(scan_result, "source_status", "")),
        "finding_count": _finding_count(scan_result),
        "blocks_finance_projection": bool(
            getattr(scan_result, "blocks_finance_projection", False)
        ),
    }


def _issue_dedupe_scope(
    *,
    scan_key: str,
    scope: FinanceIssueScope,
) -> str:
    scope_value = scope.scope_ulid or "~"
    return f"finance.{scan_key}:{scope.scope_type}:{scope_value}"


def _dirty_message(
    *,
    scope: FinanceIssueScope,
    global_message: str,
    blocked_sentence: str,
) -> str:
    if scope.scope_type == quarantine_svc.SCOPE_GLOBAL:
        return global_message
    return (
        f"Finance isolated this issue to {scope.scope_label}. "
        f"{blocked_sentence} "
        "The rest of Finance may continue unless separately quarantined."
    )


def _scope_posture(scope: FinanceIssueScope) -> str:
    if scope.scope_type == quarantine_svc.SCOPE_GLOBAL:
        return "conservative_global"
    return "scoped"


def _open_scoped_quarantine(
    *,
    issue_ulid: str,
    scope: FinanceIssueScope,
    reason_code: str,
    message: str,
    scan_result: object,
    actor_ulid: str | None,
) -> quarantine_svc.FinanceQuarantineView:
    """Open/refresh a conservative global projection quarantine.

    This is intentionally conservative. Later scanner refinements may narrow
    scope to project/funding_demand/journal. For now, the sweep must be honest:
    if Finance cannot yet prove a smaller blast radius, staff-facing financial
    projection is globally blocked for that issue family.
    """
    return quarantine_svc.open_or_refresh_quarantine(
        source_issue_ulid=issue_ulid,
        scope_type=scope.scope_type,
        scope_ulid=scope.scope_ulid,
        scope_label=scope.scope_label,
        posture=quarantine_svc.POSTURE_PROJECTION_BLOCKED,
        message=message,
        notes={
            "reason_code": reason_code,
            "finding_count": _finding_count(scan_result),
            "scope_posture": _scope_posture(scope),
            **dict(scope.notes or {}),
        },
        actor_ulid=actor_ulid,
    )


def _specs() -> tuple[_SweepSpec, ...]:
    return (
        _SweepSpec(
            scan_key="journal_integrity",
            workflow_key="finance.journal_integrity",
            dedupe_scope="finance.journal_integrity:global",
            reason_code=JOURNAL_INTEGRITY_REASON,
            title="Finance journal integrity failure",
            dirty_message=(
                "Finance found a Journal/JournalLine integrity failure. "
                "Staff-facing financial projection is blocked until Finance "
                "classifies or resolves this issue."
            ),
            scanner=journal_integrity_scan,
            raiser=issue_svc.raise_journal_integrity_admin_issue,
            scope_inferer=infer_journal_integrity_scope,
            blocked_sentence="Staff-facing financial projection is blocked until Finance classifies or resolves this issue.",
        ),
        _SweepSpec(
            scan_key="balance_projection",
            workflow_key="finance.balance_projection",
            dedupe_scope="finance.balance_projection:global",
            reason_code=BALANCE_PROJECTION_DRIFT_REASON,
            title="Finance balance projection drift",
            dirty_message=(
                "Finance found BalanceMonthly projection drift. Projection "
                "that depends on BalanceMonthly is blocked until Finance "
                "previews and rebuilds the projection."
            ),
            scanner=balance_projection_drift_scan,
            raiser=issue_svc.raise_balance_projection_drift_admin_issue,
            scope_inferer=infer_balance_projection_scope,
            blocked_sentence="Projection that depends on BalanceMonthly is blocked until Finance previews and rebuilds the projection.",
        ),
        _SweepSpec(
            scan_key="posting_fact",
            workflow_key="finance.posting_fact",
            dedupe_scope="finance.posting_fact:global",
            reason_code=POSTING_FACT_DRIFT_REASON,
            title="Finance semantic posting fact drift",
            dirty_message=(
                "Finance found semantic posting fact drift. Calendar staff "
                "financial posture is blocked until Finance repairs or "
                "classifies the affected semantic index."
            ),
            scanner=posting_fact_drift_scan,
            raiser=issue_svc.raise_posting_fact_drift_admin_issue,
            scope_inferer=infer_posting_fact_scope,
            blocked_sentence="Calendar staff financial posture is blocked until Finance repairs or classifies the affected semantic index.",
        ),
        _SweepSpec(
            scan_key="control_state",
            workflow_key="finance.control_state",
            dedupe_scope="finance.control_state:global",
            reason_code=CONTROL_STATE_DRIFT_REASON,
            title="Finance control-state drift",
            dirty_message=(
                "Finance found Reserve or Encumbrance control-state drift. "
                "Affected financial posture is blocked until Finance reviews "
                "the control state."
            ),
            scanner=control_state_drift_scan,
            raiser=issue_svc.raise_control_state_drift_admin_issue,
            scope_inferer=infer_control_state_scope,
            blocked_sentence="Affected financial posture is blocked until Finance reviews the control state.",
        ),
        _SweepSpec(
            scan_key="ops_float",
            workflow_key="finance.ops_float",
            dedupe_scope="finance.ops_float:global",
            reason_code=OPS_FLOAT_SANITY_REASON,
            title="Finance ops-float sanity issue",
            dirty_message=(
                "Finance found OpsFloat support-state drift. Bridge-support "
                "projection is blocked until Finance reviews the issue."
            ),
            scanner=ops_float_sanity_scan,
            raiser=issue_svc.raise_ops_float_sanity_admin_issue,
            scope_inferer=infer_ops_float_scope,
            blocked_sentence="Bridge-support projection is blocked until Finance reviews the issue.",
        ),
    )


def latest_finance_sweep_run() -> FinanceSweepRunView | None:
    row = (
        db.session.execute(
            select(FinanceSweepRun)
            .order_by(
                FinanceSweepRun.ran_at_utc.desc(),
                FinanceSweepRun.ulid.desc(),
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    return _to_sweep_run_view(row)


def _persist_sweep_run(
    *,
    request_id: str,
    actor_ulid: str | None,
    scans_run: int,
    clean_count: int,
    dirty_count: int,
    issue_count: int,
    quarantine_count: int,
    outcomes: tuple[FinanceSweepOutcome, ...],
) -> FinanceSweepRun:
    row = FinanceSweepRun(
        request_id=request_id,
        actor_ulid=actor_ulid,
        ran_at_utc=now_iso8601_ms(),
        scans_run=scans_run,
        clean_count=clean_count,
        dirty_count=dirty_count,
        issue_count=issue_count,
        quarantine_count=quarantine_count,
        summary_json={
            "outcomes": [
                {
                    "scan_key": item.scan_key,
                    "reason_code": item.reason_code,
                    "ok": item.ok,
                    "finding_count": item.finding_count,
                    "issue_ulid": item.issue_ulid,
                    "quarantine_ulid": item.quarantine_ulid,
                    "message": item.message,
                }
                for item in outcomes
            ]
        },
    )
    db.session.add(row)
    db.session.flush()
    return row


def run_finance_integrity_sweep(
    *,
    actor_ulid: str | None = None,
    request_id: str | None = None,
) -> FinanceIntegritySweepResult:
    """Run Finance self-tattling diagnostics.

    Canon note for Future Dev:
      This sweep is the Finance-owned diagnostic entry point. It should raise
      or refresh FinanceAdminIssue case files and FinanceQuarantine safety
      fences. It should not auto-close issues or auto-release quarantines
      until each repair workflow has its own proof and closure rules.
    """
    sweep_request_id = request_id or new_ulid()
    outcomes: list[FinanceSweepOutcome] = []
    issue_ulids: list[str] = []
    quarantine_ulids: list[str] = []

    for spec in _specs():
        scan_result = spec.scanner()
        ok = _scan_ok(scan_result)

        if ok:
            outcomes.append(
                FinanceSweepOutcome(
                    scan_key=spec.scan_key,
                    reason_code=spec.reason_code,
                    ok=True,
                    finding_count=0,
                    issue_ulid=None,
                    quarantine_ulid=None,
                    message="clean",
                )
            )
            continue

        scope = spec.scope_inferer(scan_result)
        issue = spec.raiser(
            scan_result=scan_result,
            request_id=sweep_request_id,
            actor_ulid=actor_ulid,
            dedupe_scope=_issue_dedupe_scope(
                scan_key=spec.scan_key,
                scope=scope,
            ),
        )
        quarantine = _open_scoped_quarantine(
            issue_ulid=issue.issue_ulid,
            scope=scope,
            reason_code=spec.reason_code,
            message=_dirty_message(
                scope=scope,
                global_message=spec.dirty_message,
                blocked_sentence=spec.blocked_sentence,
            ),
            scan_result=scan_result,
            actor_ulid=actor_ulid,
        )

        issue_ulids.append(issue.issue_ulid)
        quarantine_ulids.append(quarantine.quarantine_ulid)

        outcomes.append(
            FinanceSweepOutcome(
                scan_key=spec.scan_key,
                reason_code=spec.reason_code,
                ok=False,
                finding_count=_finding_count(scan_result),
                issue_ulid=issue.issue_ulid,
                quarantine_ulid=quarantine.quarantine_ulid,
                message=spec.dirty_message,
            )
        )

    dirty_count = sum(1 for outcome in outcomes if not outcome.ok)

    sweep_row = _persist_sweep_run(
        request_id=sweep_request_id,
        actor_ulid=actor_ulid,
        scans_run=len(outcomes),
        clean_count=len(outcomes) - dirty_count,
        dirty_count=dirty_count,
        issue_count=len(issue_ulids),
        quarantine_count=len(quarantine_ulids),
        outcomes=tuple(outcomes),
    )

    return FinanceIntegritySweepResult(
        request_id=sweep_request_id,
        sweep_run_ulid=sweep_row.ulid,
        scans_run=len(outcomes),
        clean_count=len(outcomes) - dirty_count,
        dirty_count=dirty_count,
        issue_ulids=tuple(issue_ulids),
        quarantine_ulids=tuple(quarantine_ulids),
        outcomes=tuple(outcomes),
    )


__all__ = [
    "FinanceSweepOutcome",
    "FinanceSweepRunView",
    "FinanceIntegritySweepResult",
    "latest_finance_sweep_run",
    "run_finance_integrity_sweep",
]
