# tests/slices/finance/test_admin_issue_repair_services.py

from __future__ import annotations

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.admin.models import AdminAlert
from app.slices.finance.admin_issue_repair_services import (
    balance_projection_rebuild_preview,
    commit_balance_projection_rebuild,
    commit_posting_fact_drift_repair,
    posting_fact_drift_repair_preview,
)
from app.slices.finance.admin_issue_services import (
    raise_balance_projection_drift_admin_issue,
    raise_integrity_admin_issue,
    raise_posting_fact_drift_admin_issue,
)
from app.slices.finance.models import (
    BalanceMonthly,
    FinanceAdminIssue,
    FinancePostingFact,
    FinanceQuarantine,
    JournalLine,
)
from app.slices.finance.quarantine_services import (
    POSTURE_PROJECTION_BLOCKED,
    SCOPE_GLOBAL,
    STATUS_ACTIVE,
    open_or_refresh_quarantine,
)
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    balance_projection_drift_scan,
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


def _iso_for_period(period_key: str) -> str:
    return f"{period_key}-15T12:00:00.000Z"


def _post_journal_for_period(
    period_key: str, amount_cents: int = 1200
) -> None:
    funding_demand_ulid = new_ulid()
    post_journal(
        source="test",
        external_ref_ulid=new_ulid(),
        happened_at_utc=_iso_for_period(period_key),
        currency="USD",
        memo="balance preview test journal",
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


def _balance_issue_for_period(period_key: str) -> str:
    scan = balance_projection_drift_scan(
        period_from=period_key,
        period_to=period_key,
    )
    assert scan.ok is False

    view = raise_balance_projection_drift_admin_issue(
        scan_result=scan,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    db.session.flush()
    return view.issue_ulid


def _alert_for_issue(issue: FinanceAdminIssue) -> AdminAlert:
    query = (
        db.session.query(AdminAlert)
        .filter(AdminAlert.source_slice == "finance")
        .filter(AdminAlert.reason_code == issue.reason_code)
        .filter(AdminAlert.request_id == issue.request_id)
    )
    if issue.target_ulid is None:
        query = query.filter(AdminAlert.target_ulid.is_(None))
    else:
        query = query.filter(AdminAlert.target_ulid == issue.target_ulid)
    return query.one()


def test_balance_projection_rebuild_preview_records_expected_update(app):
    with app.app_context():
        _seed_refs()
        period_key = "2099-10"
        _post_journal_for_period(period_key, amount_cents=2200)

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one()
        )
        row.net_cents += 17
        db.session.flush()

        issue_ulid = _balance_issue_for_period(period_key)

        preview = balance_projection_rebuild_preview(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert preview.issue_ulid == issue_ulid
        assert preview.reason_code == BALANCE_PROJECTION_DRIFT_REASON
        assert preview.period_keys == (period_key,)
        assert preview.rows_updated == 1
        assert preview.rows_added == 0
        assert preview.rows_deleted == 0

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.preview_json["kind"] == (
            "balance_projection_rebuild_preview"
        )
        assert issue.preview_json["rows_updated"] == 1
        assert issue.preview_json["updated"][0]["before"]["net_cents"] == 2217
        assert issue.preview_json["updated"][0]["after"]["net_cents"] == 2200

        # Preview must not repair BalanceMonthly.
        db.session.refresh(row)
        assert row.net_cents == 2217


def test_balance_projection_rebuild_preview_records_added_and_deleted(app):
    with app.app_context():
        _seed_refs()
        period_key = "2099-11"
        _post_journal_for_period(period_key, amount_cents=1300)

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one()
        )
        db.session.delete(row)

        db.session.add(
            BalanceMonthly(
                account_code="1010",
                fund_code="unrestricted",
                project_ulid=None,
                period_key=period_key,
                debits_cents=999,
                credits_cents=0,
                net_cents=999,
            )
        )
        db.session.flush()

        issue_ulid = _balance_issue_for_period(period_key)

        preview = balance_projection_rebuild_preview(
            issue_ulid,
            actor_ulid=None,
        )

        assert preview.rows_added == 1
        assert preview.rows_deleted == 1
        assert preview.rows_updated == 0

        added_keys = {
            row["key"]["account_code"]
            for row in preview.preview_json["added"]
        }
        deleted_keys = {
            row["key"]["account_code"]
            for row in preview.preview_json["deleted"]
        }

        assert "1000" in added_keys
        assert "1010" in deleted_keys


def test_balance_projection_rebuild_preview_rejects_wrong_issue_type(app):
    with app.app_context():
        _seed_refs()
        view = raise_integrity_admin_issue(
            reason_code="failure_finance_journal_integrity",
            request_id=new_ulid(),
            title="Wrong issue",
            summary="Not a balance projection issue.",
            detection={"finding_count": 1},
            workflow_key="finance.journal_integrity",
            target_ulid=None,
            actor_ulid=None,
        )
        db.session.flush()

        try:
            balance_projection_rebuild_preview(
                view.issue_ulid,
                actor_ulid=None,
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "Balance projection preview requires" in str(exc)


def test_balance_projection_rebuild_preview_requires_period_evidence(app):
    with app.app_context():
        _seed_refs()
        view = raise_integrity_admin_issue(
            reason_code=BALANCE_PROJECTION_DRIFT_REASON,
            request_id=new_ulid(),
            title="Balance drift",
            summary="Missing period evidence.",
            detection={
                "finding_count": 1,
                "findings": [
                    {
                        "code": "finance_balance_projection_missing_row",
                        "context": {},
                    }
                ],
            },
            workflow_key="finance.balance_projection",
            target_ulid=None,
            actor_ulid=None,
        )
        db.session.flush()

        try:
            balance_projection_rebuild_preview(
                view.issue_ulid,
                actor_ulid=None,
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "no period_key evidence" in str(exc)


def test_commit_balance_projection_rebuild_repairs_update_and_closes(app):
    with app.app_context():
        _seed_refs()
        period_key = "2099-12"
        _post_journal_for_period(period_key, amount_cents=2400)

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one()
        )
        row.net_cents += 31
        db.session.flush()

        issue_ulid = _balance_issue_for_period(period_key)
        balance_projection_rebuild_preview(
            issue_ulid,
            actor_ulid=new_ulid(),
        )

        actor_ulid = new_ulid()
        result = commit_balance_projection_rebuild(
            issue_ulid,
            actor_ulid=actor_ulid,
        )
        db.session.flush()

        assert result.rescan_ok is True
        assert result.issue_closed is True
        assert result.rows_updated == 1
        assert result.rows_added == 0
        assert result.rows_deleted == 0

        db.session.refresh(row)
        assert row.net_cents == 2400

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "resolved"
        assert issue.source_status == "closed"
        assert issue.close_reason == "balance_projection_rebuilt"
        assert issue.resolution_json["rescan_ok"] is True

        alert = _alert_for_issue(issue)
        assert alert.admin_status == "source_closed"
        assert alert.close_reason == "balance_projection_rebuilt"


def test_commit_balance_projection_rebuild_adds_and_deletes_rows(app):
    with app.app_context():
        _seed_refs()
        period_key = "2100-01"
        _post_journal_for_period(period_key, amount_cents=1500)

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one()
        )
        db.session.delete(row)
        db.session.add(
            BalanceMonthly(
                account_code="1010",
                fund_code="unrestricted",
                project_ulid=None,
                period_key=period_key,
                debits_cents=777,
                credits_cents=0,
                net_cents=777,
            )
        )
        db.session.flush()

        issue_ulid = _balance_issue_for_period(period_key)
        preview = balance_projection_rebuild_preview(
            issue_ulid,
            actor_ulid=None,
        )
        assert preview.rows_added == 1
        assert preview.rows_deleted == 1

        result = commit_balance_projection_rebuild(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        assert result.rescan_ok is True
        assert result.issue_closed is True
        assert result.rows_added == 1
        assert result.rows_deleted == 1

        restored = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one_or_none()
        )
        stale = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1010")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one_or_none()
        )

        assert restored is not None
        assert restored.net_cents == 1500
        assert stale is None


def test_commit_balance_projection_rebuild_requires_preview(app):
    with app.app_context():
        _seed_refs()
        period_key = "2100-02"
        _post_journal_for_period(period_key, amount_cents=1600)

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one()
        )
        row.net_cents += 1
        db.session.flush()

        issue_ulid = _balance_issue_for_period(period_key)

        try:
            commit_balance_projection_rebuild(
                issue_ulid,
                actor_ulid=new_ulid(),
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "requires a current preview" in str(exc)


def test_commit_balance_projection_rebuild_rejects_stale_preview(app):
    with app.app_context():
        _seed_refs()
        period_key = "2100-03"
        _post_journal_for_period(period_key, amount_cents=1700)

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one()
        )
        row.net_cents += 5
        db.session.flush()

        issue_ulid = _balance_issue_for_period(period_key)
        balance_projection_rebuild_preview(
            issue_ulid,
            actor_ulid=None,
        )

        row.net_cents += 1
        db.session.flush()

        try:
            commit_balance_projection_rebuild(
                issue_ulid,
                actor_ulid=new_ulid(),
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "preview is stale" in str(exc)


def _post_income_for_period(
    *,
    period_key: str,
    amount_cents: int = 2500,
) -> str:
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
            "source_ref_ulid": new_ulid(),
            "funding_demand_ulid": new_ulid(),
            "request_id": new_ulid(),
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


def _posting_fact_issue_for_period(period_key: str) -> str:
    scan = posting_fact_drift_scan(
        period_from=period_key,
        period_to=period_key,
    )
    assert scan.ok is False

    view = raise_posting_fact_drift_admin_issue(
        scan_result=scan,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    db.session.flush()
    return view.issue_ulid


def test_posting_fact_repair_preview_marks_existing_fact_repairable(app):
    with app.app_context():
        _seed_refs()
        period_key = "2100-10"
        journal_ulid = _post_income_for_period(
            period_key=period_key,
            amount_cents=3100,
        )

        fact = _fact_for_journal(journal_ulid)
        expected_key = fact.idempotency_key
        fact.amount_cents = 3101
        wrong_key = f"wrong-key-{new_ulid()}"
        fact.idempotency_key = wrong_key
        db.session.flush()

        issue_ulid = _posting_fact_issue_for_period(period_key)

        preview = posting_fact_drift_repair_preview(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert preview.issue_ulid == issue_ulid
        assert preview.repairable_count == 1
        assert preview.manual_review_count == 0
        assert "amount_cents" in preview.fields_changed
        assert "idempotency_key" in preview.fields_changed

        repair = preview.preview_json["repairable"][0]
        assert repair["fact_ulid"] == fact.ulid
        assert repair["before"]["amount_cents"] == 3101
        assert repair["after"]["amount_cents"] == 3100
        assert repair["before"]["idempotency_key"] == wrong_key
        assert repair["after"]["idempotency_key"] == expected_key

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.preview_json["kind"] == (
            "posting_fact_drift_repair_preview"
        )

        # Preview must not mutate the fact row.
        db.session.refresh(fact)
        assert fact.amount_cents == 3101
        assert fact.idempotency_key == wrong_key


def test_posting_fact_repair_preview_rejects_wrong_issue_type(app):
    with app.app_context():
        _seed_refs()
        view = raise_integrity_admin_issue(
            reason_code="failure_finance_journal_integrity",
            request_id=new_ulid(),
            title="Wrong issue",
            summary="Not a posting fact issue.",
            detection={"finding_count": 1},
            workflow_key="finance.journal_integrity",
            target_ulid=None,
            actor_ulid=None,
        )
        db.session.flush()

        try:
            posting_fact_drift_repair_preview(
                view.issue_ulid,
                actor_ulid=None,
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "PostingFact repair preview requires" in str(exc)


def test_posting_fact_repair_preview_classifies_missing_fact_manual(app):
    with app.app_context():
        _seed_refs()
        period_key = "2100-11"
        funding_demand_ulid = new_ulid()

        post_journal(
            source="income",
            external_ref_ulid=new_ulid(),
            happened_at_utc=_iso_for_period(period_key),
            currency="USD",
            memo="semantic journal missing fact",
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

        issue_ulid = _posting_fact_issue_for_period(period_key)
        preview = posting_fact_drift_repair_preview(
            issue_ulid,
            actor_ulid=None,
        )

        assert preview.repairable_count == 0
        assert preview.manual_review_count == 1
        assert preview.preview_json["manual_review"][0]["code"] == (
            "finance_posting_fact_missing_for_semantic_journal"
        )


def test_posting_fact_repair_preview_refuses_dirty_journal_truth(app):
    with app.app_context():
        _seed_refs()
        period_key = "2100-12"
        journal_ulid = _post_income_for_period(
            period_key=period_key,
            amount_cents=2200,
        )
        fact = _fact_for_journal(journal_ulid)
        fact.amount_cents = 2201

        line = (
            db.session.query(JournalLine)
            .filter(JournalLine.journal_ulid == journal_ulid)
            .filter(JournalLine.amount_cents < 0)
            .one()
        )
        line.amount_cents = -2100
        db.session.flush()

        issue_ulid = _posting_fact_issue_for_period(period_key)
        preview = posting_fact_drift_repair_preview(
            issue_ulid,
            actor_ulid=None,
        )

        assert preview.repairable_count == 0
        assert preview.manual_review_count == 1
        manual = preview.preview_json["manual_review"][0]
        assert manual["code"] == "finance_posting_fact_journal_not_clean"
        assert manual["reason"] == "journal_integrity_blocks_fact_repair"


def test_commit_posting_fact_repair_updates_fact_closes_and_releases(app):
    with app.app_context():
        _seed_refs()
        period_key = "2101-01"
        journal_ulid = _post_income_for_period(
            period_key=period_key,
            amount_cents=3100,
        )

        fact = _fact_for_journal(journal_ulid)
        expected_key = fact.idempotency_key
        fact.idempotency_key = f"wrong-key-{new_ulid()}"
        fact.amount_cents = 3101
        db.session.flush()

        issue_ulid = _posting_fact_issue_for_period(period_key)
        open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_GLOBAL,
            scope_ulid=None,
            scope_label="Finance projection",
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Posting fact drift blocks projection.",
            actor_ulid=None,
        )
        posting_fact_drift_repair_preview(
            issue_ulid,
            actor_ulid=None,
        )

        result = commit_posting_fact_drift_repair(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert result.rescan_ok is True
        assert result.issue_closed is True
        assert result.facts_updated == 1
        assert result.manual_review_count == 0
        assert result.quarantines_released == 1

        db.session.refresh(fact)
        assert fact.amount_cents == 3100
        assert fact.idempotency_key == expected_key

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "resolved"
        assert issue.source_status == "closed"
        assert issue.close_reason == "posting_fact_repaired"
        assert issue.resolution_json["rescan_ok"] is True

        alert = _alert_for_issue(issue)
        assert alert.admin_status == "source_closed"
        assert alert.close_reason == "posting_fact_repaired"


def test_commit_posting_fact_repair_requires_preview(app):
    with app.app_context():
        _seed_refs()
        period_key = "2101-02"
        journal_ulid = _post_income_for_period(
            period_key=period_key,
            amount_cents=1900,
        )
        fact = _fact_for_journal(journal_ulid)
        fact.amount_cents = 1901
        db.session.flush()

        issue_ulid = _posting_fact_issue_for_period(period_key)

        try:
            commit_posting_fact_drift_repair(
                issue_ulid,
                actor_ulid=new_ulid(),
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "requires a current preview" in str(exc)


def test_commit_posting_fact_repair_rejects_stale_preview(app):
    with app.app_context():
        _seed_refs()
        period_key = "2101-03"
        journal_ulid = _post_income_for_period(
            period_key=period_key,
            amount_cents=2000,
        )
        fact = _fact_for_journal(journal_ulid)
        fact.amount_cents = 2001
        db.session.flush()

        issue_ulid = _posting_fact_issue_for_period(period_key)
        posting_fact_drift_repair_preview(
            issue_ulid,
            actor_ulid=None,
        )

        fact.amount_cents = 2002
        db.session.flush()

        try:
            commit_posting_fact_drift_repair(
                issue_ulid,
                actor_ulid=new_ulid(),
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "preview is stale" in str(exc)


def test_commit_posting_fact_repair_leaves_open_when_manual_remains(app):
    with app.app_context():
        _seed_refs()
        period_key = "2101-04"

        journal_ulid = _post_income_for_period(
            period_key=period_key,
            amount_cents=2600,
        )
        fact = _fact_for_journal(journal_ulid)
        fact.amount_cents = 2601

        missing_fact_fd = new_ulid()
        post_journal(
            source="income",
            external_ref_ulid=new_ulid(),
            happened_at_utc=_iso_for_period(period_key),
            currency="USD",
            memo="semantic journal missing fact in same period",
            created_by_actor=None,
            request_id=new_ulid(),
            lines=[
                {
                    "account_code": "1000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": missing_fact_fd,
                    "amount_cents": 1800,
                },
                {
                    "account_code": "4000",
                    "fund_code": "unrestricted",
                    "funding_demand_ulid": missing_fact_fd,
                    "amount_cents": -1800,
                },
            ],
        )
        db.session.flush()

        issue_ulid = _posting_fact_issue_for_period(period_key)
        quarantine = open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_GLOBAL,
            scope_ulid=None,
            scope_label="Finance projection",
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Posting fact drift blocks projection.",
            actor_ulid=None,
        )
        preview = posting_fact_drift_repair_preview(
            issue_ulid,
            actor_ulid=None,
        )
        assert preview.repairable_count == 1
        assert preview.manual_review_count == 1

        result = commit_posting_fact_drift_repair(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert result.facts_updated == 1
        assert result.rescan_ok is False
        assert result.issue_closed is False
        assert result.manual_review_count == 1
        assert result.quarantines_released == 0

        db.session.refresh(fact)
        assert fact.amount_cents == 2600

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "in_review"
        assert issue.source_status == "open"
        assert issue.resolution_json["rescan_ok"] is False
        assert issue.resolution_json["rescan_findings"]

        row = db.session.get(FinanceQuarantine, quarantine.quarantine_ulid)
        assert row is not None
        assert row.status == STATUS_ACTIVE
