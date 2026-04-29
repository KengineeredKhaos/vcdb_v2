# tests/slices/finance/test_admin_issue_resolution_services.py

from __future__ import annotations

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.admin.models import AdminAlert
from app.slices.finance.admin_issue_resolution_services import (
    close_journal_integrity_after_clean_rescan,
    confirm_journal_integrity_still_blocked,
    mark_journal_integrity_false_positive_after_clean_rescan,
    mark_journal_integrity_manual_review_required,
    mark_journal_integrity_reversal_required,
)
from app.slices.finance.admin_issue_services import (
    raise_integrity_admin_issue,
)
from app.slices.finance.models import (
    FinanceAdminIssue,
    FinanceQuarantine,
    Journal,
    JournalLine,
)
from app.slices.finance.quarantine_services import (
    POSTURE_PROJECTION_BLOCKED,
    SCOPE_GLOBAL,
    STATUS_ACTIVE,
    STATUS_RELEASED,
    open_or_refresh_quarantine,
)
from app.slices.finance.services_integrity import JOURNAL_INTEGRITY_REASON
from app.slices.finance.services_journal import (
    ensure_default_accounts,
    ensure_fund,
)


def _seed_refs() -> None:
    ensure_default_accounts()
    ensure_fund(
        code="unrestricted",
        name="Unrestricted Operating Fund",
        restriction="unrestricted",
    )
    db.session.flush()


def _journal_issue(*, request_id: str | None = None) -> str:
    view = raise_integrity_admin_issue(
        reason_code=JOURNAL_INTEGRITY_REASON,
        request_id=request_id or new_ulid(),
        title="Finance journal integrity failure",
        summary="Journal integrity test issue.",
        detection={"finding_count": 1},
        workflow_key="finance.journal_integrity",
        target_ulid=None,
        actor_ulid=None,
    )
    db.session.flush()
    return view.issue_ulid


def _open_global_quarantine(issue_ulid: str) -> str:
    quarantine = open_or_refresh_quarantine(
        source_issue_ulid=issue_ulid,
        scope_type=SCOPE_GLOBAL,
        scope_ulid=None,
        scope_label="Finance projection",
        posture=POSTURE_PROJECTION_BLOCKED,
        message=(
            "Finance found a Journal integrity failure. Staff-facing "
            "financial projection is blocked until resolved."
        ),
        actor_ulid=None,
    )
    db.session.flush()
    return quarantine.quarantine_ulid


def _unbalanced_journal(period_key: str = "2102-01") -> None:
    _seed_refs()
    funding_demand_ulid = new_ulid()

    journal = Journal(
        source="test",
        funding_demand_ulid=funding_demand_ulid,
        project_ulid=None,
        grant_ulid=None,
        external_ref_ulid=new_ulid(),
        currency="USD",
        period_key=period_key,
        happened_at_utc=f"{period_key}-15T12:00:00.000Z",
        posted_at_utc=f"{period_key}-15T12:00:00.000Z",
        memo="journal integrity dirty test",
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
            memo="debit",
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
            memo="short credit",
            period_key=period_key,
        )
    )
    db.session.flush()


def _alert_for_issue(issue: FinanceAdminIssue) -> AdminAlert:
    query = (
        db.session.query(AdminAlert)
        .filter(AdminAlert.source_slice == "finance")
        .filter(AdminAlert.reason_code == issue.reason_code)
        .filter(AdminAlert.request_id == issue.request_id)
    )
    return query.one()


def test_confirm_journal_integrity_still_blocked_keeps_issue_open(app):
    with app.app_context():
        _seed_refs()
        issue_ulid = _journal_issue()
        quarantine_ulid = _open_global_quarantine(issue_ulid)

        result = confirm_journal_integrity_still_blocked(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert result.issue_closed is False
        assert result.active_quarantine_count == 1
        assert (
            result.resolution_json["last_action"] == "confirm_still_blocked"
        )

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "in_review"
        assert issue.source_status == "open"

        quarantine = db.session.get(FinanceQuarantine, quarantine_ulid)
        assert quarantine is not None
        assert quarantine.status == STATUS_ACTIVE

        alert = _alert_for_issue(issue)
        assert alert.admin_status == "in_review"


def test_mark_journal_integrity_manual_review_required(app):
    with app.app_context():
        _seed_refs()
        issue_ulid = _journal_issue()
        _open_global_quarantine(issue_ulid)

        result = mark_journal_integrity_manual_review_required(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert result.issue_closed is False
        assert result.resolution_json["recommended_path"] == (
            "manual_accounting_review"
        )

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "in_review"
        assert issue.source_status == "open"


def test_mark_journal_integrity_reversal_required(app):
    with app.app_context():
        _seed_refs()
        issue_ulid = _journal_issue()
        _open_global_quarantine(issue_ulid)

        result = mark_journal_integrity_reversal_required(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert result.issue_closed is False
        assert result.resolution_json["recommended_path"] == (
            "reversal_or_adjustment_required"
        )

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "in_review"
        assert issue.source_status == "open"


def test_mark_journal_integrity_false_positive_after_clean_rescan(app):
    with app.app_context():
        _seed_refs()
        issue_ulid = _journal_issue()
        quarantine_ulid = _open_global_quarantine(issue_ulid)

        result = mark_journal_integrity_false_positive_after_clean_rescan(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert result.issue_closed is True
        assert result.active_quarantine_count == 0
        assert result.resolution_json["rescan_ok"] is True

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "false_positive"
        assert issue.source_status == "closed"
        assert issue.close_reason == "journal_integrity_false_positive"

        quarantine = db.session.get(FinanceQuarantine, quarantine_ulid)
        assert quarantine is not None
        assert quarantine.status == STATUS_RELEASED

        alert = _alert_for_issue(issue)
        assert alert.admin_status == "source_closed"


def test_close_journal_integrity_after_clean_rescan(app):
    with app.app_context():
        _seed_refs()
        issue_ulid = _journal_issue()
        quarantine_ulid = _open_global_quarantine(issue_ulid)

        result = close_journal_integrity_after_clean_rescan(
            issue_ulid,
            actor_ulid=new_ulid(),
        )
        db.session.flush()

        assert result.issue_closed is True
        assert result.active_quarantine_count == 0
        assert result.resolution_json["rescan_ok"] is True

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "resolved"
        assert issue.source_status == "closed"
        assert issue.close_reason == "journal_integrity_clean_rescan"

        quarantine = db.session.get(FinanceQuarantine, quarantine_ulid)
        assert quarantine is not None
        assert quarantine.status == STATUS_RELEASED


def test_false_positive_refuses_dirty_rescan(app):
    with app.app_context():
        _seed_refs()
        _unbalanced_journal("2102-02")
        issue_ulid = _journal_issue()
        _open_global_quarantine(issue_ulid)

        try:
            mark_journal_integrity_false_positive_after_clean_rescan(
                issue_ulid,
                actor_ulid=new_ulid(),
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "rescan is still dirty" in str(exc)
