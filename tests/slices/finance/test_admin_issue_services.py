# tests/slices/finance/test_admin_issue_services.py

from __future__ import annotations

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.admin.models import AdminAlert
from app.slices.finance.admin_issue_services import (
    ISSUE_STATUS_IN_REVIEW,
    ISSUE_STATUS_RESOLVED,
    close_integrity_admin_issue,
    integrity_review_get,
    raise_integrity_admin_issue,
    set_issue_oper_note,
    start_integrity_review,
)
from app.slices.finance.models import FinanceAdminIssue


def _admin_alert_for_issue(issue: FinanceAdminIssue) -> AdminAlert:
    row = (
        db.session.query(AdminAlert)
        .filter(AdminAlert.source_slice == "finance")
        .filter(AdminAlert.reason_code == issue.reason_code)
        .filter(AdminAlert.request_id == issue.request_id)
        .filter(AdminAlert.target_ulid == issue.target_ulid)
        .one()
    )
    return row


def test_raise_integrity_admin_issue_creates_finance_issue_and_alert(app):
    with app.app_context():
        request_id = new_ulid()
        target_ulid = new_ulid()

        view = raise_integrity_admin_issue(
            reason_code="failure_finance_journal_integrity",
            request_id=request_id,
            title="Journal integrity failure",
            summary="A Journal/JournalLine integrity issue was detected.",
            detection={
                "finding_count": 1,
                "findings": [{"code": "finance_journal_unbalanced"}],
            },
            workflow_key="finance.journal_integrity",
            target_ulid=target_ulid,
            actor_ulid=None,
        )
        db.session.flush()

        issue = db.session.get(FinanceAdminIssue, view.issue_ulid)
        assert issue is not None
        assert issue.reason_code == "failure_finance_journal_integrity"
        assert issue.request_id == request_id
        assert issue.target_ulid == target_ulid
        assert issue.issue_status == "open"
        assert issue.source_status == "open"
        assert issue.detection_json["finding_count"] == 1

        alert = _admin_alert_for_issue(issue)
        assert alert.workflow_key == "finance.journal_integrity"
        assert alert.admin_status == "open"
        assert alert.context_json["issue_ulid"] == issue.ulid
        assert alert.resolution_target_json["route_name"] == (
            "finance.admin_issue_detail"
        )
        assert issue.admin_alert_ulid == alert.ulid


def test_raise_integrity_admin_issue_is_deduped_by_request_reason_target(app):
    with app.app_context():
        request_id = new_ulid()
        target_ulid = new_ulid()

        first = raise_integrity_admin_issue(
            reason_code="anomaly_finance_posting_fact_drift",
            request_id=request_id,
            title="First title",
            summary="First summary",
            detection={"finding_count": 1},
            workflow_key="finance.posting_fact",
            target_ulid=target_ulid,
            actor_ulid=None,
        )
        second = raise_integrity_admin_issue(
            reason_code="anomaly_finance_posting_fact_drift",
            request_id=request_id,
            title="Updated title",
            summary="Updated summary",
            detection={"finding_count": 2},
            workflow_key="finance.posting_fact",
            target_ulid=target_ulid,
            actor_ulid=None,
        )
        db.session.flush()

        assert second.issue_ulid == first.issue_ulid

        rows = (
            db.session.query(FinanceAdminIssue)
            .filter(
                FinanceAdminIssue.reason_code
                == "anomaly_finance_posting_fact_drift"
            )
            .filter(FinanceAdminIssue.request_id == request_id)
            .filter(FinanceAdminIssue.target_ulid == target_ulid)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].title == "Updated title"
        assert rows[0].detection_json["finding_count"] == 2

        alerts = (
            db.session.query(AdminAlert).filter(
                AdminAlert.source_slice == "finance",
                AdminAlert.reason_code == "anomaly_finance_posting_fact_drift",
                AdminAlert.request_id == request_id,
                AdminAlert.target_ulid == target_ulid,
            ).all()
        )
        assert len(alerts) == 1
        assert alerts[0].title == "Updated title"


def test_set_issue_oper_note_updates_issue(app):
    with app.app_context():
        view = raise_integrity_admin_issue(
            reason_code="anomaly_finance_control_state_drift",
            request_id=new_ulid(),
            title="Control drift",
            summary="Reserve or Encumbrance drift was detected.",
            detection={"finding_count": 1},
            workflow_key="finance.control_state",
            target_ulid=new_ulid(),
            actor_ulid=None,
        )
        db.session.flush()

        updated = set_issue_oper_note(
            view.issue_ulid,
            actor_ulid=new_ulid(),
            oper_note="Called treasurer 14:20. Awaiting callback.",
        )

        assert updated.oper_note == "Called treasurer 14:20. Awaiting callback."


def test_review_and_close_integrity_admin_issue_updates_alert(app):
    with app.app_context():
        request_id = new_ulid()
        actor_ulid = new_ulid()

        view = raise_integrity_admin_issue(
            reason_code="anomaly_finance_balance_projection_drift",
            request_id=request_id,
            title="Balance projection drift",
            summary="BalanceMonthly drift was detected.",
            detection={"finding_count": 1},
            workflow_key="finance.balance_projection",
            target_ulid=None,
            actor_ulid=None,
        )
        db.session.flush()

        review = start_integrity_review(
            view.issue_ulid,
            actor_ulid=actor_ulid,
        )
        assert review.issue_status == ISSUE_STATUS_IN_REVIEW
        assert review.source_status == "in_review"
        assert review.review_started_by_actor_ulid == actor_ulid

        issue = db.session.get(FinanceAdminIssue, view.issue_ulid)
        assert issue is not None
        alert = _admin_alert_for_issue(issue)
        assert alert.admin_status == "in_review"

        closed = close_integrity_admin_issue(
            view.issue_ulid,
            actor_ulid=actor_ulid,
            close_reason="resolved_by_rescan",
            issue_status=ISSUE_STATUS_RESOLVED,
            resolution={"rescan": "clean"},
        )
        assert closed.issue_status == ISSUE_STATUS_RESOLVED
        assert closed.source_status == "closed"
        assert closed.close_reason == "resolved_by_rescan"
        assert closed.resolution["rescan"] == "clean"

        db.session.flush()
        alert = _admin_alert_for_issue(issue)
        assert alert.admin_status == "source_closed"
        assert alert.close_reason == "resolved_by_rescan"
        assert alert.closed_at_utc is not None


def test_integrity_review_get_returns_view(app):
    with app.app_context():
        view = raise_integrity_admin_issue(
            reason_code="anomaly_finance_control_state_drift",
            request_id=new_ulid(),
            title="Control drift",
            summary="Reserve or Encumbrance drift was detected.",
            detection={"finding_count": 1},
            workflow_key="finance.control_state",
            target_ulid=new_ulid(),
            actor_ulid=None,
        )
        db.session.flush()

        loaded = integrity_review_get(view.issue_ulid)

        assert loaded.issue_ulid == view.issue_ulid
        assert loaded.reason_code == "anomaly_finance_control_state_drift"
        assert loaded.detection["finding_count"] == 1
