# tests/slices/finance/test_services_integrity.py

from __future__ import annotations

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.finance.models import (
    BalanceMonthly,
    Encumbrance,
    FinancePostingFact,
    Journal,
    JournalLine,
    OpsFloat,
    Reserve,
)
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    CONTROL_STATE_DRIFT_REASON,
    JOURNAL_INTEGRITY_REASON,
    OPS_FLOAT_SANITY_REASON,
    POSTING_FACT_DRIFT_REASON,
    balance_projection_drift_scan,
    control_state_drift_scan,
    journal_integrity_scan,
    ops_float_sanity_scan,
    posting_fact_drift_scan,
)
from app.slices.finance.services_journal import (
    ensure_default_accounts,
    ensure_fund,
    post_journal,
)
from app.slices.finance.services_semantic_posting import post_income


def _seed_finance_refs() -> None:
    ensure_default_accounts()
    ensure_fund(
        code="unrestricted",
        name="Unrestricted Operating Fund",
        restriction="unrestricted",
    )
    db.session.flush()


def _codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


def test_journal_integrity_scan_ok_for_posted_journal(app):
    with app.app_context():
        _seed_finance_refs()
        funding_demand_ulid = new_ulid()

        post_journal(
            source="test",
            external_ref_ulid=new_ulid(),
            happened_at_utc=now_iso8601_ms(),
            currency="USD",
            memo="integrity test clean journal",
            created_by_actor=None,
            request_id=new_ulid(),
            lines=[
                {
                    "account_code": "1000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": 5000,
                },
                {
                    "account_code": "4000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": -5000,
                },
            ],
        )

        result = journal_integrity_scan()

        assert result.ok is True
        assert result.reason_code == JOURNAL_INTEGRITY_REASON
        assert result.source_status == "clean"
        assert result.finding_count == 0
        assert result.blocks_finance_projection is False


def test_journal_integrity_scan_detects_unbalanced_journal(app):
    with app.app_context():
        _seed_finance_refs()

        happened_at = now_iso8601_ms()
        period_key = happened_at[:7]
        funding_demand_ulid = new_ulid()

        journal = Journal(
            source="test",
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=None,
            grant_ulid=None,
            external_ref_ulid=new_ulid(),
            currency="USD",
            period_key=period_key,
            happened_at_utc=happened_at,
            posted_at_utc=happened_at,
            memo="intentionally broken unbalanced journal",
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
                amount_cents=5000,
                memo="one-sided test line",
                period_key=period_key,
            )
        )
        db.session.flush()

        result = journal_integrity_scan()
        codes = _codes(result)

        assert result.ok is False
        assert result.source_status == "open"
        assert result.blocks_finance_projection is True
        assert "finance_journal_missing_lines" in codes
        assert "finance_journal_unbalanced" in codes


def test_journal_integrity_scan_detects_reference_and_header_drift(app):
    with app.app_context():
        _seed_finance_refs()

        happened_at = now_iso8601_ms()
        period_key = happened_at[:7]
        funding_demand_ulid = new_ulid()
        line_funding_demand_ulid = new_ulid()

        journal = Journal(
            source="test",
            funding_demand_ulid=funding_demand_ulid,
            project_ulid=None,
            grant_ulid=None,
            external_ref_ulid=new_ulid(),
            currency="USD",
            period_key=period_key,
            happened_at_utc=happened_at,
            posted_at_utc=happened_at,
            memo="intentionally drifted journal",
            created_by_actor=None,
        )
        db.session.add(journal)
        db.session.flush()

        db.session.add(
            JournalLine(
                journal_ulid=journal.ulid,
                funding_demand_ulid=line_funding_demand_ulid,
                seq=1,
                account_code="9999",
                fund_code="ghost_fund",
                amount_cents=1000,
                memo="unknown account and fund",
                period_key="1999-01",
            )
        )
        db.session.add(
            JournalLine(
                journal_ulid=journal.ulid,
                funding_demand_ulid=funding_demand_ulid,
                seq=2,
                account_code="4000",
                fund_code="unrestricted",
                amount_cents=-1000,
                memo="balancing line",
                period_key=period_key,
            )
        )
        db.session.flush()

        result = journal_integrity_scan()
        codes = _codes(result)

        assert result.ok is False
        assert "finance_journal_funding_demand_mismatch" in codes
        assert "finance_journal_period_mismatch" in codes
        assert "finance_journal_unknown_account" in codes
        assert "finance_journal_unknown_fund" in codes

        context = result.admin_context()
        assert context["reason_code"] == JOURNAL_INTEGRITY_REASON
        assert context["source_status"] == "open"
        assert context["blocks_finance_projection"] is True


def _iso_for_period(period_key: str) -> str:
    """Return a stable ISO timestamp inside a test-only accounting period."""
    return f"{period_key}-15T12:00:00.000Z"


def test_balance_projection_drift_scan_ok_for_posted_journal(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-01"
        funding_demand_ulid = new_ulid()

        post_journal(
            source="test",
            external_ref_ulid=new_ulid(),
            happened_at_utc=_iso_for_period(period_key),
            currency="USD",
            memo="projection clean journal",
            created_by_actor=None,
            request_id=new_ulid(),
            lines=[
                {
                    "account_code": "1000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": 7500,
                },
                {
                    "account_code": "4000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": -7500,
                },
            ],
        )

        result = balance_projection_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )

        assert result.ok is True
        assert result.reason_code == BALANCE_PROJECTION_DRIFT_REASON
        assert result.source_status == "clean"
        assert result.finding_count == 0
        assert result.blocks_finance_projection is False


def test_balance_projection_drift_scan_detects_missing_row(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-02"
        funding_demand_ulid = new_ulid()

        post_journal(
            source="test",
            external_ref_ulid=new_ulid(),
            happened_at_utc=_iso_for_period(period_key),
            currency="USD",
            memo="projection missing row journal",
            created_by_actor=None,
            request_id=new_ulid(),
            lines=[
                {
                    "account_code": "1000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": 1200,
                },
                {
                    "account_code": "4000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": -1200,
                },
            ],
        )

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .filter(BalanceMonthly.project_ulid.is_(None))
            .filter(BalanceMonthly.period_key == period_key)
            .one()
        )
        db.session.delete(row)
        db.session.flush()

        result = balance_projection_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        codes = _codes(result)

        assert result.ok is False
        assert "finance_balance_projection_missing_row" in codes


def test_balance_projection_drift_scan_detects_amount_mismatch(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-03"
        funding_demand_ulid = new_ulid()

        post_journal(
            source="test",
            external_ref_ulid=new_ulid(),
            happened_at_utc=_iso_for_period(period_key),
            currency="USD",
            memo="projection mismatch journal",
            created_by_actor=None,
            request_id=new_ulid(),
            lines=[
                {
                    "account_code": "1000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": 3300,
                },
                {
                    "account_code": "4000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": -3300,
                },
            ],
        )

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .filter(BalanceMonthly.project_ulid.is_(None))
            .filter(BalanceMonthly.period_key == period_key)
            .one()
        )
        row.net_cents += 1
        db.session.flush()

        result = balance_projection_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        codes = _codes(result)

        assert result.ok is False
        assert "finance_balance_projection_amount_mismatch" in codes


def test_balance_projection_drift_scan_detects_stale_row(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-04"

        db.session.add(
            BalanceMonthly(
                account_code="1000",
                fund_code="unrestricted",
                project_ulid=None,
                period_key=period_key,
                debits_cents=900,
                credits_cents=0,
                net_cents=900,
            )
        )
        db.session.flush()

        result = balance_projection_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        codes = _codes(result)

        assert result.ok is False
        assert "finance_balance_projection_stale_row" in codes


def _post_clean_income_fact(
    *,
    amount_cents: int = 2500,
    period_key: str = "2099-05",
) -> str:
    request_id = new_ulid()
    source_ref_ulid = new_ulid()
    funding_demand_ulid = new_ulid()

    out = post_income(
        {
            "amount_cents": amount_cents,
            "happened_at_utc": _iso_for_period(period_key),
            "fund_code": "unrestricted",
            "fund_label": "Unrestricted Operating Fund",
            "fund_restriction_type": "unrestricted",
            "income_kind": "donation",
            "receipt_method": "bank",
            "source": "income",
            "source_ref_ulid": source_ref_ulid,
            "funding_demand_ulid": funding_demand_ulid,
            "request_id": request_id,
        },
        dry_run=False,
    )
    return str(out["id"])


def _fact_for_journal(journal_ulid: str) -> FinancePostingFact:
    return (
        db.session.query(FinancePostingFact)
        .filter(FinancePostingFact.journal_ulid == journal_ulid)
        .one()
    )


def test_posting_fact_drift_scan_ok_for_semantic_income(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-05"

        _post_clean_income_fact(period_key=period_key)

        result = posting_fact_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )

        assert result.ok is True
        assert result.reason_code == POSTING_FACT_DRIFT_REASON
        assert result.source_status == "clean"
        assert result.finding_count == 0
        assert result.blocks_finance_projection is False


def test_posting_fact_drift_scan_detects_missing_semantic_fact(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-07"
        funding_demand_ulid = new_ulid()

        post_journal(
            source="income",
            external_ref_ulid=new_ulid(),
            happened_at_utc=_iso_for_period(period_key),
            currency="USD",
            memo="semantic-looking journal without posting fact",
            created_by_actor=None,
            request_id=new_ulid(),
            lines=[
                {
                    "account_code": "1000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": 1800,
                },
                {
                    "account_code": "4000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": funding_demand_ulid,
                    "amount_cents": -1800,
                },
            ],
        )

        result = posting_fact_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        codes = _codes(result)

        assert result.ok is False
        assert "finance_posting_fact_missing_for_semantic_journal" in codes


def test_posting_fact_drift_scan_detects_amount_and_key_drift(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-08"
        journal_ulid = _post_clean_income_fact(
            amount_cents=3100,
            period_key=period_key,
        )
        fact = _fact_for_journal(journal_ulid)
        fact.amount_cents = 3101
        fact.idempotency_key = f"wrong-key-{new_ulid()}"
        db.session.flush()

        result = posting_fact_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        codes = _codes(result)

        assert result.ok is False
        assert "finance_posting_fact_amount_mismatch" in codes
        assert "finance_posting_fact_idempotency_key_mismatch" in codes


def test_posting_fact_drift_scan_detects_header_drift(app):
    with app.app_context():
        _seed_finance_refs()
        period_key = "2099-09"
        journal_ulid = _post_clean_income_fact(period_key=period_key)
        fact = _fact_for_journal(journal_ulid)
        fact.funding_demand_ulid = new_ulid()
        fact.source_ref_ulid = new_ulid()
        db.session.flush()

        result = posting_fact_drift_scan(
            period_from=period_key,
            period_to=period_key,
        )
        codes = _codes(result)

        assert result.ok is False
        assert "finance_posting_fact_funding_demand_mismatch" in codes
        assert "finance_posting_fact_source_ref_mismatch" in codes


def test_control_state_drift_scan_ok_for_clean_rows(app):
    with app.app_context():
        _seed_finance_refs()
        fd = new_ulid()

        db.session.add(
            Reserve(
                funding_demand_ulid=fd,
                project_ulid=None,
                grant_ulid=None,
                fund_code="unrestricted",
                amount_cents=1000,
                status="active",
                source="test",
                source_ref_ulid=new_ulid(),
                memo=None,
            )
        )
        db.session.add(
            Encumbrance(
                funding_demand_ulid=fd,
                project_ulid=None,
                grant_ulid=None,
                fund_code="unrestricted",
                amount_cents=1000,
                relieved_cents=250,
                status="active",
                source="test",
                source_ref_ulid=new_ulid(),
                memo=None,
            )
        )
        db.session.flush()

        result = control_state_drift_scan()

        assert result.ok is True
        assert result.reason_code == CONTROL_STATE_DRIFT_REASON
        assert result.source_status == "clean"
        assert result.finding_count == 0


def test_control_state_drift_scan_detects_unknown_fund(app):
    with app.app_context():
        _seed_finance_refs()
        fd = new_ulid()

        db.session.add(
            Reserve(
                funding_demand_ulid=fd,
                project_ulid=None,
                grant_ulid=None,
                fund_code="ghost_fund",
                amount_cents=1000,
                status="active",
                source="test",
                source_ref_ulid=None,
                memo=None,
            )
        )
        db.session.flush()

        result = control_state_drift_scan()
        codes = _codes(result)

        assert result.ok is False
        assert "finance_reserve_unknown_fund" in codes


def test_control_state_drift_scan_detects_encumbrance_status_drift(app):
    with app.app_context():
        _seed_finance_refs()
        fd = new_ulid()

        db.session.add(
            Encumbrance(
                funding_demand_ulid=fd,
                project_ulid=None,
                grant_ulid=None,
                fund_code="unrestricted",
                amount_cents=1000,
                relieved_cents=1000,
                status="active",
                source="test",
                source_ref_ulid=None,
                memo=None,
            )
        )
        db.session.add(
            Encumbrance(
                funding_demand_ulid=new_ulid(),
                project_ulid=None,
                grant_ulid=None,
                fund_code="unrestricted",
                amount_cents=1000,
                relieved_cents=250,
                status="relieved",
                source="test",
                source_ref_ulid=None,
                memo=None,
            )
        )
        db.session.flush()

        result = control_state_drift_scan()
        codes = _codes(result)

        assert result.ok is False
        assert "finance_encumbrance_active_without_open_amount" in codes
        assert "finance_encumbrance_relieved_with_open_amount" in codes


def test_ops_float_sanity_scan_ok_for_clean_rows(app):
    with app.app_context():
        _seed_finance_refs()

        parent = OpsFloat(
            action="allocate",
            support_mode="bridge",
            source_funding_demand_ulid=new_ulid(),
            source_project_ulid=None,
            dest_funding_demand_ulid=new_ulid(),
            dest_project_ulid=None,
            fund_code="unrestricted",
            amount_cents=1000,
            status="active",
            parent_ops_float_ulid=None,
            source_ref_ulid=None,
            memo=None,
        )
        db.session.add(parent)
        db.session.flush()

        db.session.add(
            OpsFloat(
                action="repay",
                support_mode="bridge",
                source_funding_demand_ulid=parent.dest_funding_demand_ulid,
                source_project_ulid=None,
                dest_funding_demand_ulid=parent.source_funding_demand_ulid,
                dest_project_ulid=None,
                fund_code="unrestricted",
                amount_cents=250,
                status="active",
                parent_ops_float_ulid=parent.ulid,
                source_ref_ulid=None,
                memo=None,
            )
        )
        db.session.flush()

        result = ops_float_sanity_scan()

        assert result.ok is True
        assert result.reason_code == OPS_FLOAT_SANITY_REASON
        assert result.source_status == "clean"
        assert result.finding_count == 0


def test_ops_float_sanity_scan_detects_oversettled_allocation(app):
    with app.app_context():
        _seed_finance_refs()

        parent = OpsFloat(
            action="allocate",
            support_mode="bridge",
            source_funding_demand_ulid=new_ulid(),
            source_project_ulid=None,
            dest_funding_demand_ulid=new_ulid(),
            dest_project_ulid=None,
            fund_code="unrestricted",
            amount_cents=1000,
            status="active",
            parent_ops_float_ulid=None,
            source_ref_ulid=None,
            memo=None,
        )
        db.session.add(parent)
        db.session.flush()

        db.session.add(
            OpsFloat(
                action="repay",
                support_mode="bridge",
                source_funding_demand_ulid=parent.dest_funding_demand_ulid,
                source_project_ulid=None,
                dest_funding_demand_ulid=parent.source_funding_demand_ulid,
                dest_project_ulid=None,
                fund_code="unrestricted",
                amount_cents=1001,
                status="active",
                parent_ops_float_ulid=parent.ulid,
                source_ref_ulid=None,
                memo=None,
            )
        )
        db.session.flush()

        result = ops_float_sanity_scan()
        codes = _codes(result)

        assert result.ok is False
        assert "finance_ops_float_oversettled" in codes


def test_ops_float_sanity_scan_detects_parent_and_shape_drift(app):
    with app.app_context():
        _seed_finance_refs()
        same_fd = new_ulid()

        db.session.add(
            OpsFloat(
                action="allocate",
                support_mode="bridge",
                source_funding_demand_ulid=same_fd,
                source_project_ulid=None,
                dest_funding_demand_ulid=same_fd,
                dest_project_ulid=None,
                fund_code="ghost_fund",
                amount_cents=1000,
                status="active",
                parent_ops_float_ulid=new_ulid(),
                source_ref_ulid=None,
                memo=None,
            )
        )
        db.session.add(
            OpsFloat(
                action="repay",
                support_mode="bridge",
                source_funding_demand_ulid=new_ulid(),
                source_project_ulid=None,
                dest_funding_demand_ulid=new_ulid(),
                dest_project_ulid=None,
                fund_code="unrestricted",
                amount_cents=100,
                status="active",
                parent_ops_float_ulid=None,
                source_ref_ulid=None,
                memo=None,
            )
        )
        db.session.flush()

        result = ops_float_sanity_scan()
        codes = _codes(result)

        assert result.ok is False
        assert "finance_ops_float_unknown_fund" in codes
        assert "finance_ops_float_allocate_has_parent" in codes
        assert "finance_ops_float_same_source_dest" in codes
        assert "finance_ops_float_settlement_missing_parent" in codes
