# app/slices/finance/admin_issue_repair_services.py

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import (
    BalanceMonthly,
    FinanceAdminIssue,
    JournalLine,
)
from app.slices.finance.admin_issue_services import (
    ISSUE_STATUS_IN_REVIEW,
    ISSUE_STATUS_RESOLVED,
    close_integrity_admin_issue,
)
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    balance_projection_drift_scan,
)


@dataclass(frozen=True)
class BalanceProjectionRebuildPreview:
    """Preview evidence for rebuilding BalanceMonthly.

    This is intentionally not a repair result. It tells Admin/Auditor what
    Finance would change if the rebuild were committed later.
    """

    issue_ulid: str
    reason_code: str
    period_keys: tuple[str, ...]
    current_row_count: int
    expected_row_count: int
    rows_added: int
    rows_updated: int
    rows_deleted: int
    rows_unchanged: int
    preview_json: dict[str, Any]


@dataclass(frozen=True)
class BalanceProjectionRebuildCommit:
    """Commit result for rebuilding BalanceMonthly from JournalLine truth."""

    issue_ulid: str
    reason_code: str
    period_keys: tuple[str, ...]
    rows_added: int
    rows_updated: int
    rows_deleted: int
    rescan_ok: bool
    issue_closed: bool
    resolution_json: dict[str, Any]


def _get_issue(issue_ulid: str) -> FinanceAdminIssue:
    row = db.session.get(FinanceAdminIssue, issue_ulid)
    if row is None:
        raise LookupError(f"Finance admin issue not found: {issue_ulid}")
    return row


def _require_balance_issue(row: FinanceAdminIssue) -> None:
    if row.reason_code != BALANCE_PROJECTION_DRIFT_REASON:
        raise ValueError(
            "Balance projection preview requires a "
            f"{BALANCE_PROJECTION_DRIFT_REASON} issue"
        )


def _periods_from_issue(row: FinanceAdminIssue) -> tuple[str, ...]:
    """Extract affected period keys from Finance issue detection evidence.

    BalanceMonthly repair should be scoped whenever possible. The balance
    drift scanner includes period_key in every finding context. If an older
    or hand-built issue lacks that evidence, fail loudly rather than preview
    an accidental all-time rebuild.
    """

    detection = dict(row.detection_json or {})
    findings = detection.get("findings") or ()
    periods: set[str] = set()

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        context = finding.get("context") or {}
        if not isinstance(context, dict):
            continue
        period_key = str(context.get("period_key") or "").strip()
        if period_key:
            periods.add(period_key)

    if not periods:
        raise ValueError(
            "Balance projection issue has no period_key evidence; "
            "refusing unscoped rebuild preview"
        )

    return tuple(sorted(periods))


def _row_key(
    *,
    account_code: str,
    fund_code: str,
    project_ulid: str | None,
    period_key: str,
) -> tuple[str, str, str | None, str]:
    return (account_code, fund_code, project_ulid, period_key)


def _key_json(key: tuple[str, str, str | None, str]) -> dict[str, str | None]:
    account_code, fund_code, project_ulid, period_key = key
    return {
        "account_code": account_code,
        "fund_code": fund_code,
        "project_ulid": project_ulid,
        "period_key": period_key,
    }


def _balance_row_json(row: BalanceMonthly) -> dict[str, Any]:
    return {
        "account_code": row.account_code,
        "fund_code": row.fund_code,
        "project_ulid": row.project_ulid,
        "period_key": row.period_key,
        "debits_cents": int(row.debits_cents or 0),
        "credits_cents": int(row.credits_cents or 0),
        "net_cents": int(row.net_cents or 0),
    }


def _expected_row_json(
    key: tuple[str, str, str | None, str],
    bucket: dict[str, int],
) -> dict[str, Any]:
    data = _key_json(key)
    data.update(
        {
            "debits_cents": int(bucket["debits"]),
            "credits_cents": int(bucket["credits"]),
            "net_cents": int(bucket["net"]),
        }
    )
    return data


def _current_balances(
    *,
    period_keys: tuple[str, ...],
) -> dict[tuple[str, str, str | None, str], BalanceMonthly]:
    rows = db.session.execute(
        select(BalanceMonthly)
        .where(BalanceMonthly.period_key.in_(period_keys))
        .order_by(
            BalanceMonthly.period_key,
            BalanceMonthly.account_code,
            BalanceMonthly.fund_code,
            BalanceMonthly.project_ulid,
        )
    ).scalars()

    out: dict[tuple[str, str, str | None, str], BalanceMonthly] = {}
    for row in rows:
        key = _row_key(
            account_code=row.account_code,
            fund_code=row.fund_code,
            project_ulid=row.project_ulid,
            period_key=row.period_key,
        )
        out[key] = row
    return out


def _expected_balances(
    *,
    period_keys: tuple[str, ...],
) -> dict[tuple[str, str, str | None, str], dict[str, int]]:
    buckets: dict[
        tuple[str, str, str | None, str],
        dict[str, int],
    ] = defaultdict(lambda: {"debits": 0, "credits": 0, "net": 0})

    lines = db.session.execute(
        select(JournalLine)
        .where(JournalLine.period_key.in_(period_keys))
        .order_by(
            JournalLine.period_key,
            JournalLine.account_code,
            JournalLine.fund_code,
            JournalLine.project_ulid,
        )
    ).scalars()

    for line in lines:
        key = _row_key(
            account_code=line.account_code,
            fund_code=line.fund_code,
            project_ulid=line.project_ulid,
            period_key=line.period_key,
        )
        amount = int(line.amount_cents or 0)
        if amount >= 0:
            buckets[key]["debits"] += amount
        else:
            buckets[key]["credits"] += -amount
        buckets[key]["net"] += amount

    return dict(buckets)


def _same_amounts(
    row: BalanceMonthly,
    bucket: dict[str, int],
) -> bool:
    return (
        int(row.debits_cents or 0) == int(bucket["debits"])
        and int(row.credits_cents or 0) == int(bucket["credits"])
        and int(row.net_cents or 0) == int(bucket["net"])
    )


def _preview_payload(
    *,
    row: FinanceAdminIssue,
    period_keys: tuple[str, ...],
) -> dict[str, Any]:
    current = _current_balances(period_keys=period_keys)
    expected = _expected_balances(period_keys=period_keys)

    added: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    unchanged = 0

    for key in sorted(expected):
        bucket = expected[key]
        existing = current.get(key)

        if existing is None:
            added.append(
                {
                    "key": _key_json(key),
                    "before": None,
                    "after": _expected_row_json(key, bucket),
                }
            )
            continue

        if _same_amounts(existing, bucket):
            unchanged += 1
            continue

        updated.append(
            {
                "key": _key_json(key),
                "before": _balance_row_json(existing),
                "after": _expected_row_json(key, bucket),
            }
        )

    for key in sorted(current):
        if key in expected:
            continue
        deleted.append(
            {
                "key": _key_json(key),
                "before": _balance_row_json(current[key]),
                "after": None,
            }
        )

    return {
        "kind": "balance_projection_rebuild_preview",
        "generated_at_utc": now_iso8601_ms(),
        "issue_ulid": row.ulid,
        "reason_code": row.reason_code,
        "period_keys": list(period_keys),
        "current_row_count": len(current),
        "expected_row_count": len(expected),
        "rows_added": len(added),
        "rows_updated": len(updated),
        "rows_deleted": len(deleted),
        "rows_unchanged": unchanged,
        "added": added,
        "updated": updated,
        "deleted": deleted,
    }


def _preview_comparison_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return stable preview fields for stale-preview detection."""
    return {
        "period_keys": list(payload.get("period_keys") or []),
        "rows_added": int(payload.get("rows_added") or 0),
        "rows_updated": int(payload.get("rows_updated") or 0),
        "rows_deleted": int(payload.get("rows_deleted") or 0),
        "added": list(payload.get("added") or []),
        "updated": list(payload.get("updated") or []),
        "deleted": list(payload.get("deleted") or []),
    }


def _require_preview_current(
    *,
    row: FinanceAdminIssue,
    period_keys: tuple[str, ...],
) -> dict[str, Any]:
    preview = dict(row.preview_json or {})
    if preview.get("kind") != "balance_projection_rebuild_preview":
        raise ValueError(
            "Balance projection rebuild requires a current preview first"
        )

    preview_periods = tuple(
        sorted(str(p) for p in preview.get("period_keys"))
    )
    if preview_periods != period_keys:
        raise ValueError(
            "Balance projection preview period scope does not match issue"
        )

    fresh = _preview_payload(row=row, period_keys=period_keys)
    if _preview_comparison_payload(preview) != _preview_comparison_payload(
        fresh
    ):
        raise ValueError(
            "Balance projection preview is stale; regenerate preview"
        )

    return fresh


def _apply_balance_rebuild(
    *,
    period_keys: tuple[str, ...],
) -> dict[str, int]:
    """Mutate BalanceMonthly to match JournalLine truth for period_keys."""
    current = _current_balances(period_keys=period_keys)
    expected = _expected_balances(period_keys=period_keys)

    added = 0
    updated = 0
    deleted = 0

    for key, bucket in expected.items():
        account_code, fund_code, project_ulid, period_key = key
        row = current.get(key)

        if row is None:
            row = BalanceMonthly(
                account_code=account_code,
                fund_code=fund_code,
                project_ulid=project_ulid,
                period_key=period_key,
                debits_cents=int(bucket["debits"]),
                credits_cents=int(bucket["credits"]),
                net_cents=int(bucket["net"]),
            )
            db.session.add(row)
            added += 1
            continue

        if not _same_amounts(row, bucket):
            row.debits_cents = int(bucket["debits"])
            row.credits_cents = int(bucket["credits"])
            row.net_cents = int(bucket["net"])
            updated += 1

    for key, row in current.items():
        if key in expected:
            continue
        db.session.delete(row)
        deleted += 1

    db.session.flush()
    return {
        "rows_added": added,
        "rows_updated": updated,
        "rows_deleted": deleted,
    }


def _rescan_periods(period_keys: tuple[str, ...]) -> tuple[bool, list[dict]]:
    findings: list[dict[str, Any]] = []

    for period_key in period_keys:
        result = balance_projection_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        for finding in result.findings:
            findings.append(
                {
                    "code": finding.code,
                    "message": finding.message,
                    "severity": finding.severity,
                    "journal_ulid": finding.journal_ulid,
                    "journal_line_ulid": finding.journal_line_ulid,
                    "context": dict(finding.context or {}),
                }
            )

    return (not findings), findings


def _emit_rebuild_event(
    *,
    operation: str,
    row: FinanceAdminIssue,
    actor_ulid: str,
    resolution: dict[str, Any],
) -> None:
    event_bus.emit(
        domain="finance",
        operation=operation,
        request_id=row.request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        refs={
            "issue_ulid": row.ulid,
            "admin_alert_ulid": row.admin_alert_ulid,
            "period_keys": list(resolution.get("period_keys") or []),
        },
        changed={
            "rows_added": resolution.get("rows_added", 0),
            "rows_updated": resolution.get("rows_updated", 0),
            "rows_deleted": resolution.get("rows_deleted", 0),
            "rescan_ok": resolution.get("rescan_ok", False),
        },
        meta={
            "reason_code": row.reason_code,
            "source_status": row.source_status,
            "issue_status": row.issue_status,
        },
        chain_key="finance.balance",
    )


def balance_projection_rebuild_preview(
    issue_ulid: str,
    *,
    actor_ulid: str | None,
) -> BalanceProjectionRebuildPreview:
    """Preview a BalanceMonthly rebuild for a Finance-owned issue.

    Canon note for Future Dev:
      BalanceMonthly is rebuildable projection data. JournalLine is the
      authoritative money fact. This function writes preview evidence only;
      it does not mutate BalanceMonthly. Commit must remain a separate,
      explicit Admin-only action.
    """

    row = _get_issue(issue_ulid)
    _require_balance_issue(row)

    period_keys = _periods_from_issue(row)
    payload = _preview_payload(row=row, period_keys=period_keys)

    row.preview_json = payload
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="balance_projection_rebuild_previewed",
        request_id=row.request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        refs={
            "issue_ulid": row.ulid,
            "admin_alert_ulid": row.admin_alert_ulid,
            "period_keys": list(period_keys),
        },
        changed={
            "preview_kind": "balance_projection_rebuild_preview",
            "rows_added": payload["rows_added"],
            "rows_updated": payload["rows_updated"],
            "rows_deleted": payload["rows_deleted"],
        },
        meta={
            "reason_code": row.reason_code,
            "source_status": row.source_status,
            "issue_status": row.issue_status,
        },
        chain_key="finance.balance",
    )

    return BalanceProjectionRebuildPreview(
        issue_ulid=row.ulid,
        reason_code=row.reason_code,
        period_keys=period_keys,
        current_row_count=int(payload["current_row_count"]),
        expected_row_count=int(payload["expected_row_count"]),
        rows_added=int(payload["rows_added"]),
        rows_updated=int(payload["rows_updated"]),
        rows_deleted=int(payload["rows_deleted"]),
        rows_unchanged=int(payload["rows_unchanged"]),
        preview_json=payload,
    )


def commit_balance_projection_rebuild(
    issue_ulid: str,
    *,
    actor_ulid: str,
) -> BalanceProjectionRebuildCommit:
    """Commit a previewed BalanceMonthly rebuild.

    Canon note for Future Dev:
      This is the first safe Finance repair pattern:

      1. Preview and store evidence.
      2. Refuse stale previews.
      3. Mutate only rebuildable projection rows.
      4. Rescan the same scope.
      5. Close the issue only when Finance proves the projection is clean.

      Journal/JournalLine are not edited here. They are the source of truth.
    """
    row = _get_issue(issue_ulid)
    _require_balance_issue(row)

    if not actor_ulid:
        raise ValueError("actor_ulid is required for repair commit")

    period_keys = _periods_from_issue(row)
    preview = _require_preview_current(row=row, period_keys=period_keys)

    applied = _apply_balance_rebuild(period_keys=period_keys)
    rescan_ok, rescan_findings = _rescan_periods(period_keys)

    resolution = {
        "kind": "balance_projection_rebuild_commit",
        "committed_at_utc": now_iso8601_ms(),
        "issue_ulid": row.ulid,
        "reason_code": row.reason_code,
        "period_keys": list(period_keys),
        "preview_generated_at_utc": preview.get("generated_at_utc"),
        "rows_added": int(applied["rows_added"]),
        "rows_updated": int(applied["rows_updated"]),
        "rows_deleted": int(applied["rows_deleted"]),
        "rescan_ok": bool(rescan_ok),
        "rescan_findings": rescan_findings,
    }

    if rescan_ok:
        _emit_rebuild_event(
            operation="balance_projection_rebuilt",
            row=row,
            actor_ulid=actor_ulid,
            resolution=resolution,
        )
        close_integrity_admin_issue(
            row.ulid,
            actor_ulid=actor_ulid,
            close_reason="balance_projection_rebuilt",
            issue_status=ISSUE_STATUS_RESOLVED,
            resolution=resolution,
        )
        issue_closed = True
    else:
        row.issue_status = ISSUE_STATUS_IN_REVIEW
        row.source_status = "open"
        row.resolution_json = resolution
        db.session.flush()
        _emit_rebuild_event(
            operation="balance_projection_rebuild_failed_rescan",
            row=row,
            actor_ulid=actor_ulid,
            resolution=resolution,
        )
        issue_closed = False

    return BalanceProjectionRebuildCommit(
        issue_ulid=row.ulid,
        reason_code=row.reason_code,
        period_keys=period_keys,
        rows_added=int(applied["rows_added"]),
        rows_updated=int(applied["rows_updated"]),
        rows_deleted=int(applied["rows_deleted"]),
        rescan_ok=bool(rescan_ok),
        issue_closed=issue_closed,
        resolution_json=resolution,
    )


__all__ = [
    "BalanceProjectionRebuildPreview",
    "BalanceProjectionRebuildCommit",
    "balance_projection_rebuild_preview",
    "commit_balance_projection_rebuild",
]
