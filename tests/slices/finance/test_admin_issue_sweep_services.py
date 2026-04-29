# tests/slices/finance/test_admin_issue_sweep_services.py

from __future__ import annotations

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.finance.admin_issue_sweep_services import (
    latest_finance_sweep_run,
    run_finance_integrity_sweep,
)
from app.slices.finance.models import (
    BalanceMonthly,
    FinanceAdminIssue,
    FinancePostingFact,
    FinanceQuarantine,
    FinanceSweepRun,
    Journal,
    JournalLine,
)
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    JOURNAL_INTEGRITY_REASON,
    balance_projection_drift_scan,
    infer_balance_projection_scope,
    infer_posting_fact_scope,
    posting_fact_drift_scan,
)
from app.slices.finance.services_journal import (
    ensure_default_accounts,
    ensure_fund,
    post_journal,
)
from app.slices.finance.services_semantic_posting import post_income


def _seed_refs() -> None:
    ensure_default_accounts()
    ensure_fund(
        code="unrestricted",
        name="Unrestricted Operating Fund",
        restriction="unrestricted",
    )
    db.session.flush()


def _iso(period_key: str) -> str:
    return f"{period_key}-15T12:00:00.000Z"


def _post_journal_for_period(
    *,
    period_key: str,
    amount_cents: int = 1200,
) -> None:
    funding_demand_ulid = new_ulid()
    post_journal(
        source="test",
        external_ref_ulid=new_ulid(),
        happened_at_utc=_iso(period_key),
        currency="USD",
        memo="sweep balance projection test journal",
        created_by_actor=None,
        request_id=new_ulid(),
        lines=[
            {
                "account_code": "1000",
                "fund_code": "unrestricted",
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": amount_cents,
            },
            {
                "account_code": "4000",
                "fund_code": "unrestricted",
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": -amount_cents,
            },
        ],
    )


def _create_balance_projection_drift(period_key: str) -> None:
    _seed_refs()
    _post_journal_for_period(period_key=period_key, amount_cents=2100)

    row = (
        db.session.query(BalanceMonthly)
        .filter(BalanceMonthly.period_key == period_key)
        .filter(BalanceMonthly.account_code == "1000")
        .filter(BalanceMonthly.fund_code == "unrestricted")
        .one()
    )
    row.net_cents += 13
    db.session.flush()


def _create_unbalanced_journal(period_key: str) -> None:
    _seed_refs()
    ts = _iso(period_key)
    funding_demand_ulid = new_ulid()

    journal = Journal(
        source="test",
        funding_demand_ulid=funding_demand_ulid,
        project_ulid=None,
        grant_ulid=None,
        external_ref_ulid=new_ulid(),
        currency="USD",
        period_key=period_key,
        happened_at_utc=ts,
        posted_at_utc=ts,
        memo="sweep unbalanced journal",
        created_by_actor=None,
    )
    db.session.add(journal)
    db.session.flush()

    db.session.add(
        JournalLine(
            journal_ulid=journal.ulid,
            funding_demand_ulid=funding_demand_ulid,
            seq=1,
            account_code="1000",
            fund_code="unrestricted",
            amount_cents=1000,
            memo="sweep debit",
            period_key=period_key,
        )
    )
    db.session.add(
        JournalLine(
            journal_ulid=journal.ulid,
            funding_demand_ulid=funding_demand_ulid,
            seq=2,
            account_code="4000",
            fund_code="unrestricted",
            amount_cents=-900,
            memo="sweep short credit",
            period_key=period_key,
        )
    )
    db.session.flush()


def _issue_by_ulid(issue_ulid: str):
    return db.session.get(FinanceAdminIssue, issue_ulid)


def _quarantine_by_ulid(quarantine_ulid: str):
    return db.session.get(FinanceQuarantine, quarantine_ulid)


def test_finance_integrity_sweep_raises_balance_issue_and_quarantine(app):
    with app.app_context():
        _create_balance_projection_drift("2300-01")

        result = run_finance_integrity_sweep(
            request_id=new_ulid(),
            actor_ulid=None,
        )
        db.session.flush()

        assert result.scans_run == 5
        assert result.dirty_count >= 1

        outcome = next(
            item
            for item in result.outcomes
            if item.reason_code == BALANCE_PROJECTION_DRIFT_REASON
        )
        assert outcome.ok is False
        assert outcome.finding_count >= 1
        assert outcome.issue_ulid is not None
        assert outcome.quarantine_ulid is not None

        issue = _issue_by_ulid(outcome.issue_ulid)
        assert issue is not None
        assert issue.issue_status == "open"
        assert issue.source_status == "open"

        quarantine = _quarantine_by_ulid(outcome.quarantine_ulid)
        assert quarantine is not None
        assert quarantine.source_issue_ulid == issue.ulid
        assert quarantine.reason_code == BALANCE_PROJECTION_DRIFT_REASON
        assert quarantine.message.startswith("Finance found BalanceMonthly")

        sweep = (
            db.session.query(FinanceSweepRun)
            .filter(FinanceSweepRun.request_id == result.request_id)
            .one_or_none()
        )
        assert sweep is not None
        assert sweep.scans_run == 5
        assert sweep.dirty_count >= 1
        assert sweep.issue_count >= 1
        assert sweep.quarantine_count >= 1


def test_finance_integrity_sweep_records_latest_run(app):
    with app.app_context():
        _create_balance_projection_drift("2300-01")

        _first = run_finance_integrity_sweep(
            request_id=new_ulid(),
            actor_ulid=None,
        )
        second = run_finance_integrity_sweep(
            request_id=new_ulid(),
            actor_ulid=None,
        )
        db.session.flush()

        latest = latest_finance_sweep_run()
        assert latest is not None
        assert latest.request_id == second.request_id
        assert latest.sweep_run_ulid != ""


def test_finance_integrity_sweep_dedupes_repeated_runs(app):
    with app.app_context():
        _create_balance_projection_drift("2300-02")

        first = run_finance_integrity_sweep(
            request_id=new_ulid(),
            actor_ulid=None,
        )
        second = run_finance_integrity_sweep(
            request_id=new_ulid(),
            actor_ulid=None,
        )
        db.session.flush()

        assert first.dirty_count >= 1
        assert second.dirty_count >= 1

        first_outcome = next(
            item
            for item in first.outcomes
            if item.reason_code == BALANCE_PROJECTION_DRIFT_REASON
        )
        second_outcome = next(
            item
            for item in second.outcomes
            if item.reason_code == BALANCE_PROJECTION_DRIFT_REASON
        )

        assert first_outcome.issue_ulid == second_outcome.issue_ulid
        assert first_outcome.quarantine_ulid == second_outcome.quarantine_ulid

        issue = _issue_by_ulid(second_outcome.issue_ulid)
        assert issue is not None

        active_quarantines = (
            db.session.query(FinanceQuarantine)
            .filter(FinanceQuarantine.source_issue_ulid == issue.ulid)
            .filter(FinanceQuarantine.status == "active")
            .all()
        )
        assert len(active_quarantines) == 1


def test_finance_integrity_sweep_raises_journal_issue_and_quarantine(app):
    with app.app_context():
        _create_unbalanced_journal("2300-03")

        result = run_finance_integrity_sweep(
            request_id=new_ulid(),
            actor_ulid=None,
        )
        db.session.flush()

        outcome = next(
            item
            for item in result.outcomes
            if item.reason_code == JOURNAL_INTEGRITY_REASON
        )
        assert outcome.ok is False
        assert outcome.finding_count >= 1
        assert outcome.issue_ulid is not None
        assert outcome.quarantine_ulid is not None

        issue = _issue_by_ulid(outcome.issue_ulid)
        assert issue is not None

        quarantine = _quarantine_by_ulid(outcome.quarantine_ulid)
        assert quarantine is not None
        assert quarantine.source_issue_ulid == issue.ulid
        assert quarantine.reason_code == JOURNAL_INTEGRITY_REASON
        assert quarantine.scope_type in {
            "funding_demand",
            "project",
            "journal",
            "global",
        }
        assert "Staff-facing financial projection is blocked" in (
            quarantine.message
        )


def test_balance_projection_scope_infers_project(app):
    with app.app_context():
        _seed_refs()
        project_ulid = new_ulid()
        funding_demand_ulid = new_ulid()
        period_key = "2300-04"

        post_journal(
            source="test",
            external_ref_ulid=new_ulid(),
            happened_at_utc=f"{period_key}-15T12:00:00.000Z",
            currency="USD",
            memo="project scoped balance drift",
            created_by_actor=None,
            request_id=new_ulid(),
            lines=[
                {
                    "account_code": "1000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "project_ulid": project_ulid,
                    "amount_cents": 2100,
                },
                {
                    "account_code": "4000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "project_ulid": project_ulid,
                    "amount_cents": -2100,
                },
            ],
        )

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.project_ulid == project_ulid)
            .filter(BalanceMonthly.account_code == "1000")
            .one()
        )
        row.net_cents += 7
        db.session.flush()

        scan = balance_projection_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        assert scan.ok is False

        scope = infer_balance_projection_scope(scan)
        assert scope.scope_type == "project"
        assert scope.scope_ulid == project_ulid


def test_posting_fact_scope_infers_funding_demand(app):
    with app.app_context():
        _seed_refs()
        period_key = "2300-05"

        out = post_income(
            {
                "amount_cents": 2500,
                "happened_at_utc": f"{period_key}-15T12:00:00.000Z",
                "fund_code": "unrestricted",
                "fund_label": "Unrestricted Operating Fund",
                "fund_restriction_type": "unrestricted",
                "income_kind": "donation",
                "receipt_method": "bank",
                "source": "income",
                "source_ref_ulid": new_ulid(),
                "funding_demand_ulid": new_ulid(),
                "request_id": new_ulid(),
            },
            dry_run=False,
        )
        journal_ulid = str(out["id"])

        fact = (
            db.session.query(FinancePostingFact)
            .filter(FinancePostingFact.journal_ulid == journal_ulid)
            .one()
        )
        fd = fact.funding_demand_ulid
        fact.amount_cents += 1
        db.session.flush()

        scan = posting_fact_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        assert scan.ok is False

        scope = infer_posting_fact_scope(scan)
        assert scope.scope_type == "funding_demand"
        assert scope.scope_ulid == fd
