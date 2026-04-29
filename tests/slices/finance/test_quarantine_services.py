# tests/slices/finance/test_quarantine_services.py

from __future__ import annotations

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.finance.admin_issue_services import (
    raise_integrity_admin_issue,
)
from app.slices.finance.models import FinanceQuarantine
from app.slices.finance.quarantine_services import (
    POSTURE_PROJECTION_BLOCKED,
    POSTURE_PROJECTION_AND_POSTING_BLOCKED,
    SCOPE_FUNDING_DEMAND,
    SCOPE_GLOBAL,
    STATUS_ACTIVE,
    STATUS_RELEASED,
    active_quarantines_for_scope,
    open_or_refresh_quarantine,
    release_quarantine,
)


def _issue(reason_code: str = "anomaly_finance_posting_fact_drift") -> str:
    view = raise_integrity_admin_issue(
        reason_code=reason_code,
        request_id=new_ulid(),
        title="Finance issue",
        summary="Finance test issue.",
        detection={"finding_count": 1},
        workflow_key="finance.test",
        target_ulid=None,
        dedupe_scope="test.scope",
        actor_ulid=None,
    )
    db.session.flush()
    return view.issue_ulid


def test_open_quarantine_creates_active_scope(app):
    with app.app_context():
        issue_ulid = _issue()
        fd = new_ulid()

        view = open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
            scope_label="Funding Demand ABC",
            posture=POSTURE_PROJECTION_BLOCKED,
            message=(
                "Finance isolated this issue to Funding Demand ABC. "
                "Projection is blocked for this scope."
            ),
            notes={"finding_count": 1},
            actor_ulid=None,
        )
        db.session.flush()

        assert view.status == STATUS_ACTIVE
        assert view.scope_type == SCOPE_FUNDING_DEMAND
        assert view.scope_ulid == fd
        assert view.posture == POSTURE_PROJECTION_BLOCKED
        assert view.notes["finding_count"] == 1

        row = db.session.get(FinanceQuarantine, view.quarantine_ulid)
        assert row is not None
        assert row.dedupe_key.endswith(f":funding_demand:{fd}")


def test_open_quarantine_refreshes_existing_scope(app):
    with app.app_context():
        issue_ulid = _issue()
        fd = new_ulid()

        first = open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Initial quarantine.",
            actor_ulid=None,
        )
        second = open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
            posture=POSTURE_PROJECTION_AND_POSTING_BLOCKED,
            message="Refreshed quarantine.",
            notes={"refreshed": True},
            actor_ulid=None,
        )
        db.session.flush()

        assert second.quarantine_ulid == first.quarantine_ulid

        rows = (
            db.session.query(FinanceQuarantine)
            .filter(FinanceQuarantine.scope_type == SCOPE_FUNDING_DEMAND)
            .filter(FinanceQuarantine.scope_ulid == fd)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].posture == POSTURE_PROJECTION_AND_POSTING_BLOCKED
        assert rows[0].message == "Refreshed quarantine."
        assert rows[0].notes_json["refreshed"] is True


def test_release_quarantine_marks_released(app):
    with app.app_context():
        issue_ulid = _issue()
        fd = new_ulid()

        opened = open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Projection blocked.",
            actor_ulid=None,
        )

        actor_ulid = new_ulid()
        released = release_quarantine(
            opened.quarantine_ulid,
            actor_ulid=actor_ulid,
            close_reason="clean_rescan",
            notes={"rescan_ok": True},
        )
        db.session.flush()

        assert released.status == STATUS_RELEASED
        assert released.closed_by_actor_ulid == actor_ulid
        assert released.close_reason == "clean_rescan"
        assert released.notes["rescan_ok"] is True


def test_active_quarantines_for_scope_returns_only_active(app):
    with app.app_context():
        issue_ulid = _issue()
        fd = new_ulid()

        opened = open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Projection blocked.",
            actor_ulid=None,
        )
        other_fd = new_ulid()
        open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=other_fd,
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Other projection blocked.",
            actor_ulid=None,
        )

        active = active_quarantines_for_scope(
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
        )
        assert len(active) == 1
        assert active[0].quarantine_ulid == opened.quarantine_ulid

        release_quarantine(
            opened.quarantine_ulid,
            actor_ulid=new_ulid(),
            close_reason="test_release",
        )

        active = active_quarantines_for_scope(
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
        )
        assert active == ()


def test_global_quarantine_validation(app):
    with app.app_context():
        issue_ulid = _issue("failure_finance_journal_integrity")

        opened = open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_GLOBAL,
            scope_ulid=None,
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Global projection blocked.",
            actor_ulid=None,
        )
        assert opened.scope_type == SCOPE_GLOBAL
        assert opened.scope_ulid is None

        try:
            open_or_refresh_quarantine(
                source_issue_ulid=issue_ulid,
                scope_type=SCOPE_GLOBAL,
                scope_ulid=new_ulid(),
                posture=POSTURE_PROJECTION_BLOCKED,
                message="Invalid global quarantine.",
                actor_ulid=None,
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "Global Finance quarantine" in str(exc)
