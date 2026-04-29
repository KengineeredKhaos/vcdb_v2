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
    FinancePostingFact,
    Journal,
    JournalLine,
)
from app.slices.finance import quarantine_services as quarantine_svc
from app.slices.finance.admin_issue_services import (
    ISSUE_STATUS_IN_REVIEW,
    ISSUE_STATUS_RESOLVED,
    close_integrity_admin_issue,
)
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    POSTING_FACT_DRIFT_REASON,
    balance_projection_drift_scan,
    posting_fact_drift_scan,
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


@dataclass(frozen=True)
class PostingFactDriftRepairPreview:
    """Preview evidence for deterministic FinancePostingFact repair."""

    issue_ulid: str
    reason_code: str
    repairable_count: int
    manual_review_count: int
    fields_changed: tuple[str, ...]
    preview_json: dict[str, Any]


@dataclass(frozen=True)
class PostingFactDriftRepairCommit:
    """Commit result for deterministic FinancePostingFact repair."""

    issue_ulid: str
    reason_code: str
    period_keys: tuple[str, ...]
    facts_updated: int
    manual_review_count: int
    rescan_ok: bool
    issue_closed: bool
    quarantines_released: int
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


def _require_posting_fact_issue(row: FinanceAdminIssue) -> None:
    if row.reason_code != POSTING_FACT_DRIFT_REASON:
        raise ValueError(
            "PostingFact repair preview requires a "
            f"{POSTING_FACT_DRIFT_REASON} issue"
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


def _posting_fact_key(
    *,
    request_id: str,
    source: str,
    source_ref_ulid: str | None,
    semantic_key: str,
) -> str:
    source_ref = source_ref_ulid or "~"
    return ":".join((request_id, source, source_ref, semantic_key))


def _journal_lines_for(journal_ulid: str) -> list[JournalLine]:
    return list(
        db.session.execute(
            select(JournalLine)
            .where(JournalLine.journal_ulid == journal_ulid)
            .order_by(JournalLine.seq)
        )
        .scalars()
        .all()
    )


def _journal_clean_enough(journal: Journal) -> tuple[bool, list[str]]:
    """Return whether a Journal is safe as PostingFact repair truth.

    This intentionally checks only the local Journal/JournalLine facts needed
    to repair an existing semantic fact. If Journal truth is dirty, the
    PostingFact repair must refuse and classify the row for manual review.
    """
    reasons: list[str] = []
    lines = _journal_lines_for(journal.ulid)

    if len(lines) < 2:
        reasons.append("journal_has_fewer_than_two_lines")

    total = sum(int(line.amount_cents or 0) for line in lines)
    if total != 0:
        reasons.append("journal_lines_do_not_balance")

    for line in lines:
        if int(line.amount_cents or 0) == 0:
            reasons.append("journal_has_zero_amount_line")
        if line.funding_demand_ulid != journal.funding_demand_ulid:
            reasons.append("journal_line_funding_demand_mismatch")
        if line.period_key != journal.period_key:
            reasons.append("journal_line_period_mismatch")

    return (not reasons, reasons)


def _semantic_amount_from_journal(journal: Journal) -> int:
    return sum(
        int(line.amount_cents or 0)
        for line in _journal_lines_for(journal.ulid)
        if int(line.amount_cents or 0) > 0
    )


def _fact_before_json(fact: FinancePostingFact) -> dict[str, Any]:
    return {
        "fact_ulid": fact.ulid,
        "journal_ulid": fact.journal_ulid,
        "amount_cents": int(fact.amount_cents or 0),
        "funding_demand_ulid": fact.funding_demand_ulid,
        "project_ulid": fact.project_ulid,
        "source": fact.source,
        "source_ref_ulid": fact.source_ref_ulid,
        "idempotency_key": fact.idempotency_key,
    }


def _expected_fact_json(
    *,
    fact: FinancePostingFact,
    journal: Journal,
) -> dict[str, Any]:
    source = str(journal.source)
    source_ref_ulid = journal.external_ref_ulid
    return {
        "fact_ulid": fact.ulid,
        "journal_ulid": fact.journal_ulid,
        "amount_cents": _semantic_amount_from_journal(journal),
        "funding_demand_ulid": journal.funding_demand_ulid,
        "project_ulid": journal.project_ulid,
        "source": source,
        "source_ref_ulid": source_ref_ulid,
        "idempotency_key": _posting_fact_key(
            request_id=fact.request_id,
            source=source,
            source_ref_ulid=source_ref_ulid,
            semantic_key=fact.semantic_key,
        ),
    }


def _changed_fields(
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[str, ...]:
    fields = (
        "amount_cents",
        "funding_demand_ulid",
        "project_ulid",
        "source",
        "source_ref_ulid",
        "idempotency_key",
    )
    return tuple(
        field for field in fields if before.get(field) != after.get(field)
    )


def _posting_fact_preview_payload(
    *,
    row: FinanceAdminIssue,
) -> dict[str, Any]:
    detection = dict(row.detection_json or {})
    findings = detection.get("findings") or ()

    grouped_codes: dict[str, set[str]] = {}
    manual_review: list[dict[str, Any]] = []

    manual_codes = {
        "finance_posting_fact_duplicate_idempotency_key",
        "finance_posting_fact_duplicate_for_journal",
        "finance_posting_fact_missing_for_semantic_journal",
        "finance_posting_fact_orphan_journal",
    }

    for finding in findings:
        if not isinstance(finding, dict):
            manual_review.append(
                {
                    "code": "malformed_finding",
                    "message": "Finding was not a dictionary.",
                    "reason": "manual_review",
                    "context": {},
                }
            )
            continue

        code = str(finding.get("code") or "")
        message = str(finding.get("message") or "")
        context = finding.get("context") or {}
        if not isinstance(context, dict):
            context = {}

        fact_ulid = context.get("fact_ulid")
        if code in manual_codes or not fact_ulid:
            manual_review.append(
                {
                    "code": code,
                    "message": message,
                    "reason": "ambiguous_or_not_existing_fact_repair",
                    "journal_ulid": finding.get("journal_ulid"),
                    "fact_ulid": fact_ulid,
                    "context": context,
                }
            )
            continue

        grouped_codes.setdefault(str(fact_ulid), set()).add(code)

    repairable: list[dict[str, Any]] = []

    for fact_ulid, codes in sorted(grouped_codes.items()):
        fact = db.session.get(FinancePostingFact, fact_ulid)
        if fact is None:
            manual_review.append(
                {
                    "code": "finance_posting_fact_missing",
                    "message": "FinancePostingFact no longer exists.",
                    "reason": "manual_review",
                    "fact_ulid": fact_ulid,
                    "context": {"finding_codes": sorted(codes)},
                }
            )
            continue

        journal = db.session.get(Journal, fact.journal_ulid)
        if journal is None:
            manual_review.append(
                {
                    "code": "finance_posting_fact_orphan_journal",
                    "message": "FinancePostingFact points to missing Journal.",
                    "reason": "manual_review",
                    "fact_ulid": fact_ulid,
                    "journal_ulid": fact.journal_ulid,
                    "context": {"finding_codes": sorted(codes)},
                }
            )
            continue

        journal_ok, journal_reasons = _journal_clean_enough(journal)
        if not journal_ok:
            manual_review.append(
                {
                    "code": "finance_posting_fact_journal_not_clean",
                    "message": (
                        "PostingFact repair refused because Journal truth "
                        "is not clean enough to derive semantic facts."
                    ),
                    "reason": "journal_integrity_blocks_fact_repair",
                    "fact_ulid": fact_ulid,
                    "journal_ulid": journal.ulid,
                    "context": {
                        "finding_codes": sorted(codes),
                        "journal_reasons": journal_reasons,
                    },
                }
            )
            continue

        before = _fact_before_json(fact)
        after = _expected_fact_json(fact=fact, journal=journal)
        changed = _changed_fields(before, after)

        if not changed:
            manual_review.append(
                {
                    "code": "finance_posting_fact_no_change_needed",
                    "message": (
                        "Finding remains, but expected fact values match."
                    ),
                    "reason": "manual_review",
                    "fact_ulid": fact_ulid,
                    "journal_ulid": journal.ulid,
                    "context": {"finding_codes": sorted(codes)},
                }
            )
            continue

        repairable.append(
            {
                "fact_ulid": fact.ulid,
                "journal_ulid": journal.ulid,
                "finding_codes": sorted(codes),
                "fields_changed": list(changed),
                "before": before,
                "after": after,
            }
        )

    all_fields = sorted(
        {
            field
            for item in repairable
            for field in item.get("fields_changed", ())
        }
    )

    return {
        "kind": "posting_fact_drift_repair_preview",
        "generated_at_utc": now_iso8601_ms(),
        "issue_ulid": row.ulid,
        "reason_code": row.reason_code,
        "repairable_count": len(repairable),
        "manual_review_count": len(manual_review),
        "fields_changed": all_fields,
        "repairable": repairable,
        "manual_review": manual_review,
    }


def posting_fact_drift_repair_preview(
    issue_ulid: str,
    *,
    actor_ulid: str | None,
) -> PostingFactDriftRepairPreview:
    """Preview deterministic FinancePostingFact drift repair.

    Canon note for Future Dev:
      FinancePostingFact is a semantic index over Journal truth. This preview
      only proposes repairs when the existing fact row and its Journal are
      present and the Journal is clean enough to derive the corrected fields.
      Missing facts, duplicates, and dirty Journals remain manual-review
      cases until deliberately designed otherwise.
    """
    row = _get_issue(issue_ulid)
    _require_posting_fact_issue(row)

    payload = _posting_fact_preview_payload(row=row)
    row.preview_json = payload
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="posting_fact_repair_previewed",
        request_id=row.request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        refs={
            "issue_ulid": row.ulid,
            "admin_alert_ulid": row.admin_alert_ulid,
        },
        changed={
            "repairable_count": payload["repairable_count"],
            "manual_review_count": payload["manual_review_count"],
            "fields_changed": list(payload["fields_changed"]),
        },
        meta={
            "reason_code": row.reason_code,
            "source_status": row.source_status,
            "issue_status": row.issue_status,
        },
        chain_key="finance.posting_fact",
    )

    return PostingFactDriftRepairPreview(
        issue_ulid=row.ulid,
        reason_code=row.reason_code,
        repairable_count=int(payload["repairable_count"]),
        manual_review_count=int(payload["manual_review_count"]),
        fields_changed=tuple(payload["fields_changed"]),
        preview_json=payload,
    )


def _posting_fact_preview_comparison_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return stable preview fields for stale-preview detection."""
    return {
        "repairable_count": int(payload.get("repairable_count") or 0),
        "manual_review_count": int(payload.get("manual_review_count") or 0),
        "fields_changed": list(payload.get("fields_changed") or []),
        "repairable": list(payload.get("repairable") or []),
        "manual_review": list(payload.get("manual_review") or []),
    }


def _require_posting_fact_preview_current(
    row: FinanceAdminIssue,
) -> dict[str, Any]:
    preview = dict(row.preview_json or {})
    if preview.get("kind") != "posting_fact_drift_repair_preview":
        raise ValueError(
            "PostingFact repair commit requires a current preview first"
        )

    fresh = _posting_fact_preview_payload(row=row)
    if _posting_fact_preview_comparison_payload(preview) != (
        _posting_fact_preview_comparison_payload(fresh)
    ):
        raise ValueError("PostingFact repair preview is stale; regenerate")

    return fresh


def _journal_period(journal_ulid: str | None) -> str | None:
    if not journal_ulid:
        return None
    journal = db.session.get(Journal, journal_ulid)
    if journal is None:
        return None
    return journal.period_key


def _posting_fact_preview_periods(
    payload: dict[str, Any],
) -> tuple[str, ...]:
    periods: set[str] = set()

    for item in payload.get("repairable") or []:
        if not isinstance(item, dict):
            continue
        period = _journal_period(item.get("journal_ulid"))
        if period:
            periods.add(period)

    for item in payload.get("manual_review") or []:
        if not isinstance(item, dict):
            continue
        period = _journal_period(item.get("journal_ulid"))
        if period:
            periods.add(period)

    return tuple(sorted(periods))


def _apply_posting_fact_repairs(
    payload: dict[str, Any],
) -> int:
    """Apply deterministic existing-row FinancePostingFact repairs."""
    updated = 0

    for item in payload.get("repairable") or []:
        if not isinstance(item, dict):
            raise ValueError("Malformed PostingFact repair preview item")

        fact_ulid = item.get("fact_ulid")
        after = item.get("after") or {}
        if not fact_ulid or not isinstance(after, dict):
            raise ValueError("Malformed PostingFact repair preview item")

        fact = db.session.get(FinancePostingFact, fact_ulid)
        if fact is None:
            raise ValueError(
                f"FinancePostingFact disappeared before repair: {fact_ulid}"
            )

        fact.amount_cents = int(after["amount_cents"])
        fact.funding_demand_ulid = after["funding_demand_ulid"]
        fact.project_ulid = after["project_ulid"]
        fact.source = str(after["source"])
        fact.source_ref_ulid = after["source_ref_ulid"]
        fact.idempotency_key = str(after["idempotency_key"])
        updated += 1

    db.session.flush()
    return updated


def _rescan_posting_fact_periods(
    period_keys: tuple[str, ...],
) -> tuple[bool, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []

    if not period_keys:
        result = posting_fact_drift_scan()
        scan_results = (result,)
    else:
        scan_results = tuple(
            posting_fact_drift_scan(
                period_from=period_key,
                period_to=period_key,
            )
            for period_key in period_keys
        )

    for result in scan_results:
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


def _active_quarantines_for_issue(
    issue_ulid: str,
) -> tuple[quarantine_svc.FinanceQuarantineView, ...]:
    quarantines = quarantine_svc.list_quarantines_for_issue(issue_ulid)
    return tuple(
        q for q in quarantines if q.status == quarantine_svc.STATUS_ACTIVE
    )


def _emit_posting_fact_commit_event(
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
            "facts_updated": resolution.get("facts_updated", 0),
            "manual_review_count": resolution.get(
                "manual_review_count",
                0,
            ),
            "rescan_ok": resolution.get("rescan_ok", False),
            "quarantines_released": resolution.get(
                "quarantines_released",
                0,
            ),
        },
        meta={
            "reason_code": row.reason_code,
            "source_status": row.source_status,
            "issue_status": row.issue_status,
        },
        chain_key="finance.posting_fact",
    )


def commit_posting_fact_drift_repair(
    issue_ulid: str,
    *,
    actor_ulid: str,
) -> PostingFactDriftRepairCommit:
    """Commit deterministic FinancePostingFact drift repair.

    Canon note for Future Dev:
      FinancePostingFact is a semantic index over Journal truth. This commit
      may update existing fact rows only when preview proved the correction
      from clean Journal/JournalLine data. Missing facts, duplicate facts,
      duplicate idempotency keys, and dirty Journal truth remain manual-review
      cases until intentionally designed otherwise.

      Close only when rescan is clean. No dangling bits left behind in haste.
    """
    row = _get_issue(issue_ulid)
    _require_posting_fact_issue(row)

    if not actor_ulid:
        raise ValueError("actor_ulid is required for repair commit")

    preview = _require_posting_fact_preview_current(row)
    repairable = list(preview.get("repairable") or [])
    manual_review = list(preview.get("manual_review") or [])

    if not repairable:
        raise ValueError("No deterministic PostingFact repairs in preview")

    period_keys = _posting_fact_preview_periods(preview)
    facts_updated = _apply_posting_fact_repairs(preview)
    rescan_ok, rescan_findings = _rescan_posting_fact_periods(period_keys)

    active_quarantines = _active_quarantines_for_issue(row.ulid)
    quarantines_released = len(active_quarantines) if rescan_ok else 0

    resolution = {
        "kind": "posting_fact_drift_repair_commit",
        "committed_at_utc": now_iso8601_ms(),
        "issue_ulid": row.ulid,
        "reason_code": row.reason_code,
        "period_keys": list(period_keys),
        "preview_generated_at_utc": preview.get("generated_at_utc"),
        "facts_updated": facts_updated,
        "manual_review_count": len(manual_review),
        "rescan_ok": bool(rescan_ok),
        "rescan_findings": rescan_findings,
        "quarantines_released": quarantines_released,
    }

    if rescan_ok:
        _emit_posting_fact_commit_event(
            operation="posting_fact_repaired",
            row=row,
            actor_ulid=actor_ulid,
            resolution=resolution,
        )
        close_integrity_admin_issue(
            row.ulid,
            actor_ulid=actor_ulid,
            close_reason="posting_fact_repaired",
            issue_status=ISSUE_STATUS_RESOLVED,
            resolution=resolution,
        )
        for quarantine in active_quarantines:
            quarantine_svc.release_quarantine(
                quarantine.quarantine_ulid,
                actor_ulid=actor_ulid,
                close_reason="posting_fact_repaired",
                notes={"rescan_ok": True},
            )
        issue_closed = True
    else:
        row.issue_status = ISSUE_STATUS_IN_REVIEW
        row.source_status = "open"
        row.resolution_json = resolution
        db.session.flush()
        _emit_posting_fact_commit_event(
            operation="posting_fact_repair_failed_rescan",
            row=row,
            actor_ulid=actor_ulid,
            resolution=resolution,
        )
        issue_closed = False

    return PostingFactDriftRepairCommit(
        issue_ulid=row.ulid,
        reason_code=row.reason_code,
        period_keys=period_keys,
        facts_updated=facts_updated,
        manual_review_count=len(manual_review),
        rescan_ok=bool(rescan_ok),
        issue_closed=issue_closed,
        quarantines_released=quarantines_released,
        resolution_json=resolution,
    )


__all__ = [
    "BalanceProjectionRebuildPreview",
    "BalanceProjectionRebuildCommit",
    "PostingFactDriftRepairPreview",
    "PostingFactDriftRepairCommit",
    "balance_projection_rebuild_preview",
    "commit_balance_projection_rebuild",
    "posting_fact_drift_repair_preview",
    "commit_posting_fact_drift_repair",
]
