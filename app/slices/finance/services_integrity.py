# app/slices/finance/services_integrity.py

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.slices.finance.models import (
    Account,
    BalanceMonthly,
    Encumbrance,
    Fund,
    Journal,
    FinancePostingFact,
    JournalLine,
    OpsFloat,
    Reserve,
)

JOURNAL_INTEGRITY_REASON = "failure_finance_journal_integrity"

BALANCE_PROJECTION_DRIFT_REASON = "anomaly_finance_balance_projection_drift"
POSTING_FACT_DRIFT_REASON = "anomaly_finance_posting_fact_drift"
CONTROL_STATE_DRIFT_REASON = "anomaly_finance_control_state_drift"
OPS_FLOAT_SANITY_REASON = "anomaly_finance_ops_float_oversubscribed"

SEMANTIC_POSTING_SOURCES = frozenset(
    ("income", "expense", "sponsor", "sponsors", "calendar")
)


@dataclass(frozen=True)
class FinanceIntegrityFinding:
    """One PII-free Finance integrity finding.

    The finding identifies a broken Finance fact without attempting repair.
    Admin may display this evidence later, but Finance remains the owner of
    detection, truth, and repair mechanics.
    """

    code: str
    message: str
    severity: str = "failure"
    journal_ulid: str | None = None
    journal_line_ulid: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JournalIntegrityScanResult:
    """Read-only result for Journal/JournalLine integrity checks."""

    ok: bool
    reason_code: str
    source_status: str
    finding_count: int
    findings: tuple[FinanceIntegrityFinding, ...]

    @property
    def blocks_finance_projection(self) -> bool:
        """Journal integrity failures block staff-facing projections."""
        return not self.ok

    def admin_context(self) -> dict[str, Any]:
        """Small PII-free context suitable for future Admin alert payloads."""
        return {
            "reason_code": self.reason_code,
            "source_status": self.source_status,
            "finding_count": self.finding_count,
            "blocks_finance_projection": self.blocks_finance_projection,
        }


@dataclass(frozen=True)
class BalanceProjectionDriftScanResult:
    """Read-only result for BalanceMonthly projection drift checks."""

    ok: bool
    reason_code: str
    source_status: str
    finding_count: int
    findings: tuple[FinanceIntegrityFinding, ...]

    @property
    def blocks_finance_projection(self) -> bool:
        """Balance drift blocks BalanceMonthly-derived projections only."""
        return not self.ok

    def admin_context(self) -> dict[str, Any]:
        """Small PII-free context suitable for future Admin alert payloads."""
        return {
            "reason_code": self.reason_code,
            "source_status": self.source_status,
            "finding_count": self.finding_count,
            "blocks_finance_projection": (self.blocks_finance_projection),
        }


@dataclass(frozen=True)
class PostingFactDriftScanResult:
    """Read-only result for FinancePostingFact drift checks."""

    ok: bool
    reason_code: str
    source_status: str
    finding_count: int
    findings: tuple[FinanceIntegrityFinding, ...]

    @property
    def blocks_finance_projection(self) -> bool:
        """Semantic fact drift blocks affected staff-facing projections."""
        return not self.ok

    def admin_context(self) -> dict[str, Any]:
        """Small PII-free context suitable for future Admin alert payloads."""
        return {
            "reason_code": self.reason_code,
            "source_status": self.source_status,
            "finding_count": self.finding_count,
            "blocks_finance_projection": (self.blocks_finance_projection),
        }


@dataclass(frozen=True)
class ControlStateDriftScanResult:
    """Read-only result for Reserve/Encumbrance control-state checks."""

    ok: bool
    reason_code: str
    source_status: str
    finding_count: int
    findings: tuple[FinanceIntegrityFinding, ...]

    @property
    def blocks_finance_projection(self) -> bool:
        """Control-state drift blocks affected funding-demand views."""
        return not self.ok

    def admin_context(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "source_status": self.source_status,
            "finding_count": self.finding_count,
            "blocks_finance_projection": (self.blocks_finance_projection),
        }


@dataclass(frozen=True)
class OpsFloatSanityScanResult:
    """Read-only result for OpsFloat support-state checks."""

    ok: bool
    reason_code: str
    source_status: str
    finding_count: int
    findings: tuple[FinanceIntegrityFinding, ...]

    @property
    def blocks_finance_projection(self) -> bool:
        """Ops-float drift blocks affected funding-demand views."""
        return not self.ok

    def admin_context(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "source_status": self.source_status,
            "finding_count": self.finding_count,
            "blocks_finance_projection": (self.blocks_finance_projection),
        }


def _finding(
    *,
    code: str,
    message: str,
    journal_ulid: str | None = None,
    journal_line_ulid: str | None = None,
    context: dict[str, Any] | None = None,
) -> FinanceIntegrityFinding:
    return FinanceIntegrityFinding(
        code=code,
        message=message,
        journal_ulid=journal_ulid,
        journal_line_ulid=journal_line_ulid,
        context=dict(context or {}),
    )


def _known_account_codes() -> set[str]:
    return set(db.session.execute(select(Account.code)).scalars().all())


def _known_fund_codes() -> set[str]:
    return set(db.session.execute(select(Fund.code)).scalars().all())


def _journal_lines(journal_ulid: str) -> list[JournalLine]:
    return list(
        db.session.execute(
            select(JournalLine)
            .where(JournalLine.journal_ulid == journal_ulid)
            .order_by(JournalLine.seq)
        )
        .scalars()
        .all()
    )


def _orphan_lines() -> list[JournalLine]:
    return list(
        db.session.execute(
            select(JournalLine)
            .outerjoin(Journal, JournalLine.journal_ulid == Journal.ulid)
            .where(Journal.ulid.is_(None))
            .order_by(JournalLine.journal_ulid, JournalLine.seq)
        )
        .scalars()
        .all()
    )


def journal_integrity_scan() -> JournalIntegrityScanResult:
    """Scan Finance's authoritative posted money spine.

    This function is deliberately read-only. It does not repair, close,
    write Ledger events, or upsert Admin alerts.

    Canon note for Future Dev:
      Journal and JournalLine are authoritative money facts. If these facts
      are wrong, Finance should correct them with reversal/adjustment entries
      or an explicitly documented manual resolution path. Rebuildable
      projections may be rebuilt later, but this scanner must not edit money
      truth just because it found an ugly fact.
    """
    known_accounts = _known_account_codes()
    known_funds = _known_fund_codes()
    findings: list[FinanceIntegrityFinding] = []

    for line in _orphan_lines():
        findings.append(
            _finding(
                code="finance_journal_orphan_line",
                message="JournalLine points to a missing Journal.",
                journal_ulid=line.journal_ulid,
                journal_line_ulid=line.ulid,
                context={"seq": line.seq},
            )
        )

    journals = list(
        db.session.execute(select(Journal).order_by(Journal.ulid))
        .scalars()
        .all()
    )

    for journal in journals:
        lines = _journal_lines(journal.ulid)

        if not journal.funding_demand_ulid:
            findings.append(
                _finding(
                    code="finance_journal_missing_funding_demand",
                    message="Journal is missing funding_demand_ulid.",
                    journal_ulid=journal.ulid,
                )
            )
        elif len(str(journal.funding_demand_ulid)) != 26:
            findings.append(
                _finding(
                    code="finance_journal_bad_funding_demand",
                    message="Journal funding_demand_ulid is not a ULID.",
                    journal_ulid=journal.ulid,
                )
            )

        if len(lines) < 2:
            findings.append(
                _finding(
                    code="finance_journal_missing_lines",
                    message="Journal must have at least two lines.",
                    journal_ulid=journal.ulid,
                    context={"line_count": len(lines)},
                )
            )

        total = sum(int(line.amount_cents or 0) for line in lines)
        if total != 0:
            findings.append(
                _finding(
                    code="finance_journal_unbalanced",
                    message="Journal lines do not sum to zero.",
                    journal_ulid=journal.ulid,
                    context={"sum_amount_cents": total},
                )
            )

        for line in lines:
            if int(line.amount_cents or 0) == 0:
                findings.append(
                    _finding(
                        code="finance_journal_zero_line",
                        message="JournalLine amount_cents cannot be zero.",
                        journal_ulid=journal.ulid,
                        journal_line_ulid=line.ulid,
                        context={"seq": line.seq},
                    )
                )

            if not line.funding_demand_ulid:
                findings.append(
                    _finding(
                        code=("finance_journal_line_missing_funding_demand"),
                        message=(
                            "JournalLine is missing funding_demand_ulid."
                        ),
                        journal_ulid=journal.ulid,
                        journal_line_ulid=line.ulid,
                        context={"seq": line.seq},
                    )
                )
            elif len(str(line.funding_demand_ulid)) != 26:
                findings.append(
                    _finding(
                        code="finance_journal_line_bad_funding_demand",
                        message=(
                            "JournalLine funding_demand_ulid is not a ULID."
                        ),
                        journal_ulid=journal.ulid,
                        journal_line_ulid=line.ulid,
                        context={"seq": line.seq},
                    )
                )
            elif line.funding_demand_ulid != journal.funding_demand_ulid:
                findings.append(
                    _finding(
                        code="finance_journal_funding_demand_mismatch",
                        message=(
                            "JournalLine funding_demand_ulid does not "
                            "match Journal header."
                        ),
                        journal_ulid=journal.ulid,
                        journal_line_ulid=line.ulid,
                        context={"seq": line.seq},
                    )
                )

            if line.period_key != journal.period_key:
                findings.append(
                    _finding(
                        code="finance_journal_period_mismatch",
                        message=(
                            "JournalLine period_key does not match "
                            "Journal."
                        ),
                        journal_ulid=journal.ulid,
                        journal_line_ulid=line.ulid,
                        context={
                            "seq": line.seq,
                            "journal_period_key": journal.period_key,
                            "line_period_key": line.period_key,
                        },
                    )
                )

            if line.account_code not in known_accounts:
                findings.append(
                    _finding(
                        code="finance_journal_unknown_account",
                        message="JournalLine account_code is unknown.",
                        journal_ulid=journal.ulid,
                        journal_line_ulid=line.ulid,
                        context={
                            "seq": line.seq,
                            "account_code": line.account_code,
                        },
                    )
                )

            if line.fund_code not in known_funds:
                findings.append(
                    _finding(
                        code="finance_journal_unknown_fund",
                        message="JournalLine fund_code is unknown.",
                        journal_ulid=journal.ulid,
                        journal_line_ulid=line.ulid,
                        context={
                            "seq": line.seq,
                            "fund_code": line.fund_code,
                        },
                    )
                )

    ok = not findings
    return JournalIntegrityScanResult(
        ok=ok,
        reason_code=JOURNAL_INTEGRITY_REASON,
        source_status="clean" if ok else "open",
        finding_count=len(findings),
        findings=tuple(findings),
    )


def _balance_key_from_line(
    line: JournalLine,
) -> tuple[str, str, str | None, str]:
    return (
        str(line.account_code),
        str(line.fund_code),
        line.project_ulid,
        str(line.period_key),
    )


def _balance_key_from_row(
    row: BalanceMonthly,
) -> tuple[str, str, str | None, str]:
    return (
        str(row.account_code),
        str(row.fund_code),
        row.project_ulid,
        str(row.period_key),
    )


def _projection_bucket_from_lines(
    *,
    period_from: str | None = None,
    period_to: str | None = None,
) -> dict[tuple[str, str, str | None, str], dict[str, int]]:
    stmt = select(JournalLine)
    if period_from is not None:
        stmt = stmt.where(JournalLine.period_key >= period_from)
    if period_to is not None:
        stmt = stmt.where(JournalLine.period_key <= period_to)

    buckets: dict[
        tuple[str, str, str | None, str],
        dict[str, int],
    ] = defaultdict(lambda: {"debits": 0, "credits": 0, "net": 0})

    for line in db.session.execute(stmt).scalars().all():
        key = _balance_key_from_line(line)
        amount = int(line.amount_cents or 0)
        if amount >= 0:
            buckets[key]["debits"] += amount
        else:
            buckets[key]["credits"] += -amount
        buckets[key]["net"] += amount

    return dict(buckets)


def _projection_rows(
    *,
    period_from: str | None = None,
    period_to: str | None = None,
) -> list[BalanceMonthly]:
    stmt = select(BalanceMonthly)
    if period_from is not None:
        stmt = stmt.where(BalanceMonthly.period_key >= period_from)
    if period_to is not None:
        stmt = stmt.where(BalanceMonthly.period_key <= period_to)

    return list(db.session.execute(stmt).scalars().all())


def balance_projection_drift_scan(
    *,
    period_from: str | None = None,
    period_to: str | None = None,
) -> BalanceProjectionDriftScanResult:
    """Compare BalanceMonthly projection rows to JournalLine truth.

    This function is deliberately read-only. It does not call
    rebuild_balances(), does not emit Ledger events, and does not upsert
    Admin alerts.

    Canon note for Future Dev:
      BalanceMonthly is a rebuildable projection. JournalLine is the
      authoritative money fact source. Drift here is repairable by previewing
      and rebuilding BalanceMonthly from JournalLine, but this scanner only
      reports the mismatch so Admin/Auditor can see what Finance detected.
    """
    expected = _projection_bucket_from_lines(
        period_from=period_from,
        period_to=period_to,
    )
    rows = _projection_rows(period_from=period_from, period_to=period_to)
    actual_by_key = {_balance_key_from_row(row): row for row in rows}

    findings: list[FinanceIntegrityFinding] = []

    for key, bucket in sorted(expected.items()):
        row = actual_by_key.get(key)
        acct, fund, project, period = key

        if row is None:
            findings.append(
                _finding(
                    code="finance_balance_projection_missing_row",
                    message=(
                        "BalanceMonthly row missing for JournalLine "
                        "activity."
                    ),
                    context={
                        "account_code": acct,
                        "fund_code": fund,
                        "project_ulid": project,
                        "period_key": period,
                        "expected_debits_cents": bucket["debits"],
                        "expected_credits_cents": bucket["credits"],
                        "expected_net_cents": bucket["net"],
                    },
                )
            )
            continue

        actual_debits = int(row.debits_cents or 0)
        actual_credits = int(row.credits_cents or 0)
        actual_net = int(row.net_cents or 0)

        if (
            actual_debits != bucket["debits"]
            or actual_credits != bucket["credits"]
            or actual_net != bucket["net"]
        ):
            findings.append(
                _finding(
                    code="finance_balance_projection_amount_mismatch",
                    message=(
                        "BalanceMonthly row does not match JournalLine "
                        "rollup."
                    ),
                    context={
                        "account_code": acct,
                        "fund_code": fund,
                        "project_ulid": project,
                        "period_key": period,
                        "expected_debits_cents": bucket["debits"],
                        "actual_debits_cents": actual_debits,
                        "expected_credits_cents": bucket["credits"],
                        "actual_credits_cents": actual_credits,
                        "expected_net_cents": bucket["net"],
                        "actual_net_cents": actual_net,
                    },
                )
            )

    for key, row in sorted(actual_by_key.items()):
        if key in expected:
            continue

        acct, fund, project, period = key
        findings.append(
            _finding(
                code="finance_balance_projection_stale_row",
                message=(
                    "BalanceMonthly row has no matching JournalLine "
                    "activity."
                ),
                context={
                    "account_code": acct,
                    "fund_code": fund,
                    "project_ulid": project,
                    "period_key": period,
                    "actual_debits_cents": int(row.debits_cents or 0),
                    "actual_credits_cents": int(row.credits_cents or 0),
                    "actual_net_cents": int(row.net_cents or 0),
                },
            )
        )

    ok = not findings
    return BalanceProjectionDriftScanResult(
        ok=ok,
        reason_code=BALANCE_PROJECTION_DRIFT_REASON,
        source_status="clean" if ok else "open",
        finding_count=len(findings),
        findings=tuple(findings),
    )


def _posting_fact_idempotency_key(fact: FinancePostingFact) -> str:
    source_ref = fact.source_ref_ulid or "~"
    return ":".join(
        (
            str(fact.request_id),
            str(fact.source),
            str(source_ref),
            str(fact.semantic_key),
        )
    )


def _expected_fact_amount_from_journal(journal_ulid: str) -> int:
    """Return the semantic posted amount implied by JournalLine rows.

    Current semantic posting writes one positive line and one negative line.
    Summing positive lines keeps this robust if a future semantic post splits
    a debit across multiple positive lines while remaining balanced.
    """
    lines = _journal_lines(journal_ulid)
    return sum(
        int(line.amount_cents or 0)
        for line in lines
        if int(line.amount_cents or 0) > 0
    )


def _semantic_source(source: str | None) -> bool:
    return str(source or "").strip().lower() in SEMANTIC_POSTING_SOURCES


def _period_in_scope(
    period_key: str | None,
    *,
    period_from: str | None,
    period_to: str | None,
) -> bool:
    period = str(period_key or "").strip()
    if not period:
        return False
    if period_from is not None and period < period_from:
        return False
    if period_to is not None and period > period_to:
        return False
    return True


def _fact_period_key(
    fact: FinancePostingFact,
    journal: Journal | None,
) -> str | None:
    if journal is not None:
        return journal.period_key
    return str(fact.happened_at_utc or "")[:7]


def _facts_by_journal(
    facts: list[FinancePostingFact],
) -> dict[str, list[FinancePostingFact]]:
    out: dict[str, list[FinancePostingFact]] = {}
    for fact in facts:
        out.setdefault(fact.journal_ulid, []).append(fact)
    return out


def posting_fact_drift_scan(
    *,
    period_from: str | None = None,
    period_to: str | None = None,
) -> PostingFactDriftScanResult:
    """Compare FinancePostingFact rows to Journal truth.

    This function is deliberately read-only. It does not create missing facts,
    does not repair idempotency keys, and does not emit Admin/Ledger events.

    Canon note for Future Dev:
      FinancePostingFact is a semantic index over authoritative Journal
      truth. Calendar staff-facing money views depend on these rows to answer
      questions like "received by income kind" and "spent by expense kind."
      Drift here must be visible before Calendar is allowed to present
      financial posture as safe.

      Optional period filters are for diagnostics/tests and future scoped
      Admin review. The default remains global because production integrity
      checks should see the whole Finance semantic index unless a caller
      deliberately narrows the review window.
    """
    findings: list[FinanceIntegrityFinding] = []

    facts = list(
        db.session.execute(
            select(FinancePostingFact).order_by(FinancePostingFact.ulid)
        )
        .scalars()
        .all()
    )
    scoped_pairs: list[tuple[FinancePostingFact, Journal | None]] = []
    for fact in facts:
        journal = db.session.get(Journal, fact.journal_ulid)
        if not _period_in_scope(
            _fact_period_key(fact, journal),
            period_from=period_from,
            period_to=period_to,
        ):
            continue
        scoped_pairs.append((fact, journal))

    scoped_facts = [fact for fact, _journal in scoped_pairs]
    facts_by_journal = _facts_by_journal(scoped_facts)

    duplicate_counts = Counter(
        fact.idempotency_key for fact in scoped_facts if fact.idempotency_key
    )
    for key, count in sorted(duplicate_counts.items()):
        if count <= 1:
            continue
        findings.append(
            _finding(
                code="finance_posting_fact_duplicate_idempotency_key",
                message=(
                    "FinancePostingFact idempotency_key appears more "
                    "than once."
                ),
                context={
                    "idempotency_key": key,
                    "count": int(count),
                },
            )
        )

    for fact, journal in scoped_pairs:
        expected_key = _posting_fact_idempotency_key(fact)
        if not fact.idempotency_key:
            findings.append(
                _finding(
                    code="finance_posting_fact_missing_idempotency_key",
                    message=(
                        "FinancePostingFact is missing idempotency_key."
                    ),
                    journal_ulid=fact.journal_ulid,
                    context={"fact_ulid": fact.ulid},
                )
            )
        elif fact.idempotency_key != expected_key:
            findings.append(
                _finding(
                    code="finance_posting_fact_idempotency_key_mismatch",
                    message=(
                        "FinancePostingFact idempotency_key does not "
                        "match request/source/semantic key."
                    ),
                    journal_ulid=fact.journal_ulid,
                    context={
                        "fact_ulid": fact.ulid,
                        "expected_idempotency_key": expected_key,
                        "actual_idempotency_key": fact.idempotency_key,
                    },
                )
            )

        if journal is None:
            findings.append(
                _finding(
                    code="finance_posting_fact_orphan_journal",
                    message=(
                        "FinancePostingFact points to a missing Journal."
                    ),
                    journal_ulid=fact.journal_ulid,
                    context={"fact_ulid": fact.ulid},
                )
            )
            continue

        if len(facts_by_journal.get(fact.journal_ulid, ())) > 1:
            findings.append(
                _finding(
                    code="finance_posting_fact_duplicate_for_journal",
                    message=(
                        "More than one FinancePostingFact points to the "
                        "same Journal."
                    ),
                    journal_ulid=fact.journal_ulid,
                    context={"fact_ulid": fact.ulid},
                )
            )

        if fact.source != journal.source:
            findings.append(
                _finding(
                    code="finance_posting_fact_source_mismatch",
                    message=(
                        "FinancePostingFact source does not match Journal."
                    ),
                    journal_ulid=journal.ulid,
                    context={
                        "fact_ulid": fact.ulid,
                        "journal_source": journal.source,
                        "fact_source": fact.source,
                    },
                )
            )

        if fact.source_ref_ulid != journal.external_ref_ulid:
            findings.append(
                _finding(
                    code="finance_posting_fact_source_ref_mismatch",
                    message=(
                        "FinancePostingFact source_ref_ulid does not "
                        "match Journal external_ref_ulid."
                    ),
                    journal_ulid=journal.ulid,
                    context={"fact_ulid": fact.ulid},
                )
            )

        if fact.funding_demand_ulid != journal.funding_demand_ulid:
            findings.append(
                _finding(
                    code="finance_posting_fact_funding_demand_mismatch",
                    message=(
                        "FinancePostingFact funding_demand_ulid does not "
                        "match Journal."
                    ),
                    journal_ulid=journal.ulid,
                    context={"fact_ulid": fact.ulid},
                )
            )

        if fact.project_ulid != journal.project_ulid:
            findings.append(
                _finding(
                    code="finance_posting_fact_project_mismatch",
                    message=(
                        "FinancePostingFact project_ulid does not match "
                        "Journal."
                    ),
                    journal_ulid=journal.ulid,
                    context={"fact_ulid": fact.ulid},
                )
            )

        expected_amount = _expected_fact_amount_from_journal(journal.ulid)
        if int(fact.amount_cents or 0) != expected_amount:
            findings.append(
                _finding(
                    code="finance_posting_fact_amount_mismatch",
                    message=(
                        "FinancePostingFact amount_cents does not match "
                        "JournalLine semantic amount."
                    ),
                    journal_ulid=journal.ulid,
                    context={
                        "fact_ulid": fact.ulid,
                        "expected_amount_cents": expected_amount,
                        "actual_amount_cents": int(fact.amount_cents or 0),
                    },
                )
            )

    for journal in db.session.execute(select(Journal)).scalars().all():
        if not _period_in_scope(
            journal.period_key,
            period_from=period_from,
            period_to=period_to,
        ):
            continue

        if not _semantic_source(journal.source):
            continue

        if journal.ulid in facts_by_journal:
            continue

        findings.append(
            _finding(
                code="finance_posting_fact_missing_for_semantic_journal",
                message=(
                    "Semantic-posting Journal is missing "
                    "FinancePostingFact."
                ),
                journal_ulid=journal.ulid,
                context={"journal_source": journal.source},
            )
        )

    ok = not findings
    return PostingFactDriftScanResult(
        ok=ok,
        reason_code=POSTING_FACT_DRIFT_REASON,
        source_status="clean" if ok else "open",
        finding_count=len(findings),
        findings=tuple(findings),
    )


def _open_encumbrance_cents(row: Encumbrance) -> int:
    return max(
        int(row.amount_cents or 0) - int(row.relieved_cents or 0),
        0,
    )


def _open_ops_float_cents(row: OpsFloat) -> int:
    """Return open amount for an allocate OpsFloat row.

    This intentionally does not call services_ops_float._open_amount().
    Integrity scans should be boring, local, and read-only. Keeping the math
    here avoids raising through service validation while we are trying to
    inspect possibly ugly control-state rows.
    """
    if row.action != "allocate":
        return 0

    children = (
        db.session.execute(
            select(OpsFloat).where(
                OpsFloat.parent_ops_float_ulid == row.ulid,
                OpsFloat.status == "active",
            )
        )
        .scalars()
        .all()
    )
    settled = sum(int(child.amount_cents or 0) for child in children)
    return int(row.amount_cents or 0) - int(settled)


def control_state_drift_scan() -> ControlStateDriftScanResult:
    """Scan off-GL Reserve and Encumbrance control states.

    This function is deliberately read-only. It does not release reserves,
    relieve encumbrances, emit Ledger events, or upsert Admin alerts.

    Canon note for Future Dev:
      Reserve and Encumbrance are not Journal truth, but Calendar and Finance
      projection surfaces rely on them to explain committed/open support.
      Database constraints catch impossible values. This scanner catches
      semantically inconsistent but relationally valid states.
    """
    findings: list[FinanceIntegrityFinding] = []
    known_funds = _known_fund_codes()

    reserves = (
        db.session.execute(select(Reserve).order_by(Reserve.ulid))
        .scalars()
        .all()
    )
    for row in reserves:
        if row.fund_code not in known_funds:
            findings.append(
                _finding(
                    code="finance_reserve_unknown_fund",
                    message="Reserve fund_code is unknown.",
                    context={
                        "reserve_ulid": row.ulid,
                        "fund_code": row.fund_code,
                    },
                )
            )

        if int(row.amount_cents or 0) < 0:
            findings.append(
                _finding(
                    code="finance_reserve_negative_amount",
                    message="Reserve amount_cents is negative.",
                    context={"reserve_ulid": row.ulid},
                )
            )

        if row.status == "active" and int(row.amount_cents or 0) == 0:
            findings.append(
                _finding(
                    code="finance_reserve_active_zero_amount",
                    message="Active Reserve has zero amount_cents.",
                    context={"reserve_ulid": row.ulid},
                )
            )

    encumbrances = (
        db.session.execute(select(Encumbrance).order_by(Encumbrance.ulid))
        .scalars()
        .all()
    )
    for row in encumbrances:
        amount = int(row.amount_cents or 0)
        relieved = int(row.relieved_cents or 0)
        open_cents = _open_encumbrance_cents(row)

        if row.fund_code not in known_funds:
            findings.append(
                _finding(
                    code="finance_encumbrance_unknown_fund",
                    message="Encumbrance fund_code is unknown.",
                    context={
                        "encumbrance_ulid": row.ulid,
                        "fund_code": row.fund_code,
                    },
                )
            )

        if amount < 0:
            findings.append(
                _finding(
                    code="finance_encumbrance_negative_amount",
                    message="Encumbrance amount_cents is negative.",
                    context={"encumbrance_ulid": row.ulid},
                )
            )

        if relieved < 0:
            findings.append(
                _finding(
                    code="finance_encumbrance_negative_relief",
                    message="Encumbrance relieved_cents is negative.",
                    context={"encumbrance_ulid": row.ulid},
                )
            )

        if relieved > amount:
            findings.append(
                _finding(
                    code="finance_encumbrance_over_relieved",
                    message=(
                        "Encumbrance relieved_cents exceeds amount_cents."
                    ),
                    context={"encumbrance_ulid": row.ulid},
                )
            )

        if row.status == "active" and open_cents <= 0:
            findings.append(
                _finding(
                    code="finance_encumbrance_active_without_open_amount",
                    message=(
                        "Active Encumbrance has no remaining open amount."
                    ),
                    context={
                        "encumbrance_ulid": row.ulid,
                        "amount_cents": amount,
                        "relieved_cents": relieved,
                        "open_cents": open_cents,
                    },
                )
            )

        if row.status == "relieved" and open_cents > 0:
            findings.append(
                _finding(
                    code="finance_encumbrance_relieved_with_open_amount",
                    message=("Relieved Encumbrance still has open amount."),
                    context={
                        "encumbrance_ulid": row.ulid,
                        "amount_cents": amount,
                        "relieved_cents": relieved,
                        "open_cents": open_cents,
                    },
                )
            )

    ok = not findings
    return ControlStateDriftScanResult(
        ok=ok,
        reason_code=CONTROL_STATE_DRIFT_REASON,
        source_status="clean" if ok else "open",
        finding_count=len(findings),
        findings=tuple(findings),
    )


def ops_float_sanity_scan() -> OpsFloatSanityScanResult:
    """Scan OpsFloat rows for semantically inconsistent support state.

    This function is deliberately read-only. OpsFloat rows are support-state
    facts, not Journal truth. Bad rows should be surfaced before Calendar
    shows staff a funding posture that depends on open bridge support.
    """
    findings: list[FinanceIntegrityFinding] = []
    known_funds = _known_fund_codes()

    rows = (
        db.session.execute(select(OpsFloat).order_by(OpsFloat.ulid))
        .scalars()
        .all()
    )

    for row in rows:
        amount = int(row.amount_cents or 0)

        if row.fund_code not in known_funds:
            findings.append(
                _finding(
                    code="finance_ops_float_unknown_fund",
                    message="OpsFloat fund_code is unknown.",
                    context={
                        "ops_float_ulid": row.ulid,
                        "fund_code": row.fund_code,
                    },
                )
            )

        if amount < 0:
            findings.append(
                _finding(
                    code="finance_ops_float_negative_amount",
                    message="OpsFloat amount_cents is negative.",
                    context={"ops_float_ulid": row.ulid},
                )
            )

        if row.action == "allocate":
            if row.parent_ops_float_ulid:
                findings.append(
                    _finding(
                        code="finance_ops_float_allocate_has_parent",
                        message="Allocate OpsFloat row should not have parent.",
                        context={"ops_float_ulid": row.ulid},
                    )
                )

            if row.source_funding_demand_ulid == row.dest_funding_demand_ulid:
                findings.append(
                    _finding(
                        code="finance_ops_float_same_source_dest",
                        message=(
                            "OpsFloat source and destination funding "
                            "demands must differ."
                        ),
                        context={"ops_float_ulid": row.ulid},
                    )
                )

            open_cents = _open_ops_float_cents(row)
            if open_cents < 0:
                findings.append(
                    _finding(
                        code="finance_ops_float_oversettled",
                        message=(
                            "OpsFloat settlements exceed allocation amount."
                        ),
                        context={
                            "ops_float_ulid": row.ulid,
                            "amount_cents": amount,
                            "open_cents": open_cents,
                        },
                    )
                )

        if row.action in {"repay", "forgive"}:
            if not row.parent_ops_float_ulid:
                findings.append(
                    _finding(
                        code="finance_ops_float_settlement_missing_parent",
                        message=(
                            "Repay/Forgive OpsFloat row is missing parent."
                        ),
                        context={"ops_float_ulid": row.ulid},
                    )
                )
                continue

            parent = db.session.get(OpsFloat, row.parent_ops_float_ulid)
            if parent is None:
                findings.append(
                    _finding(
                        code="finance_ops_float_settlement_orphan_parent",
                        message=(
                            "Repay/Forgive OpsFloat parent does not exist."
                        ),
                        context={
                            "ops_float_ulid": row.ulid,
                            "parent_ops_float_ulid": (
                                row.parent_ops_float_ulid
                            ),
                        },
                    )
                )
                continue

            if parent.action != "allocate":
                findings.append(
                    _finding(
                        code="finance_ops_float_parent_not_allocate",
                        message=(
                            "Repay/Forgive OpsFloat parent is not allocate."
                        ),
                        context={
                            "ops_float_ulid": row.ulid,
                            "parent_ops_float_ulid": parent.ulid,
                            "parent_action": parent.action,
                        },
                    )
                )

    ok = not findings
    return OpsFloatSanityScanResult(
        ok=ok,
        reason_code=OPS_FLOAT_SANITY_REASON,
        source_status="clean" if ok else "open",
        finding_count=len(findings),
        findings=tuple(findings),
    )


__all__ = [
    "BALANCE_PROJECTION_DRIFT_REASON",
    "CONTROL_STATE_DRIFT_REASON",
    "FinanceIntegrityFinding",
    "BalanceProjectionDriftScanResult",
    "ControlStateDriftScanResult",
    "JournalIntegrityScanResult",
    "JOURNAL_INTEGRITY_REASON",
    "OPS_FLOAT_SANITY_REASON",
    "POSTING_FACT_DRIFT_REASON",
    "OpsFloatSanityScanResult",
    "PostingFactDriftScanResult",
    "balance_projection_drift_scan",
    "control_state_drift_scan",
    "journal_integrity_scan",
    "ops_float_sanity_scan",
    "posting_fact_drift_scan",
]
