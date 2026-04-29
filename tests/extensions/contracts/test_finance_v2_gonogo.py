# tests/extensions/contracts/test_finance_v2_gonogo.py

from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import finance_v2
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.finance.admin_issue_services import (
    raise_integrity_admin_issue,
)
from app.slices.finance.models import FinanceQuarantine
from app.slices.finance.quarantine_services import (
    POSTURE_PROJECTION_BLOCKED,
    SCOPE_FUNDING_DEMAND,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    open_or_refresh_quarantine,
)


def _release_all_active_quarantines() -> None:
    now = now_iso8601_ms()
    rows = (
        db.session.query(FinanceQuarantine)
        .filter(FinanceQuarantine.status == "active")
        .all()
    )
    for row in rows:
        row.status = "released"
        row.closed_at_utc = now
        row.close_reason = "contract_test_cleanup"
    db.session.flush()


def _issue(reason_code: str = "anomaly_finance_posting_fact_drift") -> str:
    view = raise_integrity_admin_issue(
        reason_code=reason_code,
        request_id=new_ulid(),
        title="Finance issue",
        summary="Finance gating test issue.",
        detection={"finding_count": 1},
        workflow_key="finance.test",
        target_ulid=None,
        actor_ulid=None,
        dedupe_scope="finance.test.scope",
    )
    db.session.flush()
    return view.issue_ulid


def test_finance_gonogo_returns_go_without_relevant_quarantine(app):
    with app.app_context():
        _release_all_active_quarantines()

        fd = new_ulid()
        dto = finance_v2.get_funding_demand_go_nogo(fd)

        assert dto.funding_demand_ulid == fd
        assert dto.go_nogo == "go"
        assert dto.escalate_to_admin is False
        assert (
            dto.operator_message == "Finance is clear for demand processing."
        )
        assert dto.blocking_reason_codes == ()
        assert dto.blocking_scope_type is None


def test_finance_gonogo_blocks_matching_funding_demand(app):
    with app.app_context():
        _release_all_active_quarantines()

        fd = new_ulid()
        issue_ulid = _issue()

        open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_FUNDING_DEMAND,
            scope_ulid=fd,
            scope_label=f"Funding Demand {fd}",
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Funding demand blocked.",
            actor_ulid=None,
        )
        db.session.flush()

        dto = finance_v2.get_funding_demand_go_nogo(fd)

        assert dto.go_nogo == "no_go"
        assert dto.escalate_to_admin is True
        assert dto.operator_message == (
            "This funding stream is temporarily blocked. Contact Admin."
        )
        assert dto.blocking_scope_type == "funding_demand"
        assert dto.blocking_scope_ulid == fd


def test_finance_gonogo_blocks_matching_project(app):
    with app.app_context():
        _release_all_active_quarantines()

        fd = new_ulid()
        project_ulid = new_ulid()
        issue_ulid = _issue("anomaly_finance_balance_projection_drift")

        open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_PROJECT,
            scope_ulid=project_ulid,
            scope_label=f"Project {project_ulid}",
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Project blocked.",
            actor_ulid=None,
        )
        db.session.flush()

        dto = finance_v2.get_funding_demand_go_nogo(
            fd,
            project_ulid=project_ulid,
        )

        assert dto.go_nogo == "no_go"
        assert dto.escalate_to_admin is True
        assert dto.blocking_scope_type == "project"
        assert dto.blocking_scope_ulid == project_ulid


def test_finance_gonogo_global_quarantine_blocks_any_demand(app):
    with app.app_context():
        _release_all_active_quarantines()

        fd = new_ulid()
        issue_ulid = _issue("failure_finance_journal_integrity")

        open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_GLOBAL,
            scope_ulid=None,
            scope_label="Finance projection",
            posture=POSTURE_PROJECTION_BLOCKED,
            message="Global projection blocked.",
            actor_ulid=None,
        )
        db.session.flush()

        dto = finance_v2.get_funding_demand_go_nogo(fd)

        assert dto.go_nogo == "no_go"
        assert dto.escalate_to_admin is True
        assert dto.blocking_scope_type == "global"
        assert dto.blocking_scope_ulid is None
