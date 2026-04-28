# tests/slices/finance/test_admin_issue_repair_services.py

from __future__ import annotations

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.admin.models import AdminAlert
from app.slices.finance.admin_issue_repair_services import (
    balance_projection_rebuild_preview,
    commit_balance_projection_rebuild,
)
from app.slices.finance.admin_issue_services import (
    raise_balance_projection_drift_admin_issue,
    raise_integrity_admin_issue,
)
from app.slices.finance.models import BalanceMonthly, FinanceAdminIssue
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    balance_projection_drift_scan,
)
from app.slices.finance.services_journal import (
    ensure_default_accounts,
    ensure_fund,
    post_journal,
)


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
