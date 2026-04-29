# tests/slices/finance/test_admin_issue_routes.py

from __future__ import annotations

import pytest

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
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
from app.slices.finance.services_integrity import (
    BALANCE_PROJECTION_DRIFT_REASON,
    POSTING_FACT_DRIFT_REASON,
    balance_projection_drift_scan,
    posting_fact_drift_scan,
)
from app.slices.finance.services_journal import (
    ensure_default_accounts,
    ensure_fund,
    post_journal,
)
from app.slices.finance.services_semantic_posting import post_income
from app.slices.finance.quarantine_services import (
    POSTURE_PROJECTION_BLOCKED,
    SCOPE_GLOBAL,
    STATUS_ACTIVE,
    STATUS_RELEASED,
    open_or_refresh_quarantine,
)
from app.slices.finance.admin_issue_sweep_services import (
    latest_finance_sweep_run,
)


@pytest.fixture
def auditor_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "auditor"})
    return client


def _csrf(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    marker = 'name="csrf_token" value="'
    start = text.find(marker)
    assert start >= 0
    start += len(marker)
    end = text.find('"', start)
    assert end > start
    return text[start:end]


def _seed_issue() -> str:
    view = raise_integrity_admin_issue(
        reason_code="anomaly_finance_balance_projection_drift",
        request_id=new_ulid(),
        title="Balance projection drift",
        summary="BalanceMonthly drift was detected.",
        detection={"finding_count": 1},
        workflow_key="finance.balance_projection",
        target_ulid=None,
        actor_ulid=None,
    )
    db.session.commit()
    return view.issue_ulid


def _seed_finance_refs() -> None:
    ensure_default_accounts()
    ensure_fund(
        code="unrestricted",
        name="Unrestricted Operating Fund",
        restriction="unrestricted",
    )
    db.session.flush()


def _iso_for_period(period_key: str) -> str:
    return f"{period_key}-15T12:00:00.000Z"


def _unused_test_period(start_year: int = 2200) -> str:
    """Return a test-only period_key not already used in Finance rows.

    Route tests may be rerun against a dev/test database that is not freshly
    recreated every time. BalanceMonthly rebuilds from all JournalLine truth
    in a period, so hard-coded period keys make expected amounts accumulate
    across repeated test runs.
    """
    used = {
        row[0]
        for row in db.session.query(JournalLine.period_key).distinct().all()
        if row[0]
    }
    used.update(
        row[0]
        for row in db.session.query(BalanceMonthly.period_key)
        .distinct()
        .all()
        if row[0]
    )
    for year in range(start_year, start_year + 50):
        for month in range(1, 13):
            key = f"{year:04d}-{month:02d}"
            if key not in used:
                return key
    raise RuntimeError("No unused Finance test period available")


def _seed_balance_projection_issue(period_key: str = "2100-04") -> str:
    _seed_finance_refs()
    funding_demand_ulid = new_ulid()

    post_journal(
        source="test",
        external_ref_ulid=new_ulid(),
        happened_at_utc=_iso_for_period(period_key),
        currency="USD",
        memo="route balance projection repair test",
        created_by_actor=None,
        request_id=new_ulid(),
        lines=[
            {
                "account_code": "1000",
                "fund_code": "unrestricted",
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": 1900,
            },
            {
                "account_code": "4000",
                "fund_code": "unrestricted",
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": -1900,
            },
        ],
    )

    row = (
        db.session.query(BalanceMonthly)
        .filter(BalanceMonthly.period_key == period_key)
        .filter(BalanceMonthly.account_code == "1000")
        .filter(BalanceMonthly.fund_code == "unrestricted")
        .one()
    )
    row.net_cents += 9
    db.session.flush()

    scan = balance_projection_drift_scan(
        period_from=period_key,
        period_to=period_key,
    )
    view = raise_balance_projection_drift_admin_issue(
        scan_result=scan,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    db.session.commit()
    return view.issue_ulid


def _seed_journal_issue_with_quarantine() -> str:
    view = raise_integrity_admin_issue(
        reason_code="failure_finance_journal_integrity",
        request_id=new_ulid(),
        title="Finance journal integrity failure",
        summary="Journal integrity route test issue.",
        detection={"finding_count": 1},
        workflow_key="finance.journal_integrity",
        target_ulid=None,
        actor_ulid=None,
    )
    db.session.flush()
    open_or_refresh_quarantine(
        source_issue_ulid=view.issue_ulid,
        scope_type=SCOPE_GLOBAL,
        scope_ulid=None,
        scope_label="Finance projection",
        posture=POSTURE_PROJECTION_BLOCKED,
        message="Finance projection blocked.",
        actor_ulid=None,
    )
    db.session.commit()
    return view.issue_ulid


def _seed_balance_projection_drift_only(period_key: str) -> None:
    _seed_finance_refs()
    funding_demand_ulid = new_ulid()

    post_journal(
        source="test",
        external_ref_ulid=new_ulid(),
        happened_at_utc=_iso_for_period(period_key),
        currency="USD",
        memo="route sweep balance projection drift",
        created_by_actor=None,
        request_id=new_ulid(),
        lines=[
            {
                "account_code": "1000",
                "fund_code": "unrestricted",
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": 2100,
            },
            {
                "account_code": "4000",
                "fund_code": "unrestricted",
                "funding_demand_ulid": funding_demand_ulid,
                "amount_cents": -2100,
            },
        ],
    )

    row = (
        db.session.query(BalanceMonthly)
        .filter(BalanceMonthly.period_key == period_key)
        .filter(BalanceMonthly.account_code == "1000")
        .filter(BalanceMonthly.fund_code == "unrestricted")
        .one()
    )
    row.net_cents += 11
    db.session.commit()


def _seed_posting_fact_issue(period_key: str) -> tuple[str, str, str]:
    _seed_finance_refs()

    out = post_income(
        {
            "amount_cents": 2750,
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
    journal_ulid = str(out["id"])

    fact = (
        db.session.query(FinancePostingFact)
        .filter(FinancePostingFact.journal_ulid == journal_ulid)
        .one()
    )
    expected_key = fact.idempotency_key
    fact.amount_cents = 2751
    fact.idempotency_key = f"wrong-key-{new_ulid()}"
    db.session.flush()

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
    db.session.commit()
    return view.issue_ulid, fact.ulid, expected_key


def test_finance_admin_issue_index_allows_admin_and_auditor(
    app,
    admin_client,
    auditor_client,
):
    with app.app_context():
        _seed_issue()

    resp = admin_client.get("/finance/admin/issues")
    assert resp.status_code == 200
    assert "Finance issue drill-down" in resp.get_data(as_text=True)

    resp = auditor_client.get("/finance/admin/issues")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Finance issue drill-down" in body
    assert "Latest sweep" in body


def test_finance_admin_can_save_oper_note(app, admin_client):
    with app.app_context():
        issue_ulid = _seed_issue()

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(admin_client, path)

    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/oper-note",
        data={
            "csrf_token": csrf,
            "oper_note": "Called outside accountant. Awaiting callback.",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.oper_note == (
            "Called outside accountant. Awaiting callback."
        )


def test_finance_admin_issue_detail_is_readable_by_auditor(
    app,
    auditor_client,
):
    with app.app_context():
        issue_ulid = _seed_issue()

    resp = auditor_client.get(f"/finance/admin/issues/{issue_ulid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Balance projection drift" in body
    assert "Current posture" in body
    assert "Recommended next step" in body
    assert "Repair available" in body
    assert "Quarantine scope" in body
    assert "Yes — preview available" in body
    assert "Read-only auditor view" in body
    assert "Start review" not in body
    assert "Operator note" in body


def test_finance_journal_issue_detail_shows_guidance_to_auditor(
    app,
    auditor_client,
):
    with app.app_context():
        issue_ulid = _seed_journal_issue_with_quarantine()

    resp = auditor_client.get(f"/finance/admin/issues/{issue_ulid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Journal integrity guidance" in body
    assert "Current posture" in body
    assert "Recommended next step" in body
    assert "Repair available" in body
    assert "Quarantine scope" in body
    assert "No — workflow only" in body
    assert "Classify for manual review or reversal/adjustment" in body
    assert "Finance found a Journal integrity failure." in body
    assert "Staff-facing financial projection is blocked" in body
    assert "Read-only auditor view" in body
    assert "Confirm still blocked" not in body
    assert "Mark manual accounting review required" not in body
    assert "Mark reversal/adjustment required" not in body


def test_finance_issue_detail_shows_quarantine_to_auditor(
    app,
    auditor_client,
):
    with app.app_context():
        issue_ulid = _seed_issue()
        open_or_refresh_quarantine(
            source_issue_ulid=issue_ulid,
            scope_type=SCOPE_GLOBAL,
            scope_ulid=None,
            scope_label="Finance projection",
            posture=POSTURE_PROJECTION_BLOCKED,
            message=(
                "Finance isolated this issue to global projection. "
                "Staff-facing financial projection is blocked until resolved."
            ),
            notes={"finding_count": 1},
            actor_ulid=None,
        )
        db.session.commit()

    resp = auditor_client.get(f"/finance/admin/issues/{issue_ulid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Finance safety posture" in body
    assert "Current posture" in body
    assert "Projection blocked" in body
    assert "Recommended next step" in body
    assert "Run balance rebuild preview" in body
    assert "Quarantine scope" in body
    assert "Active quarantine" in body
    assert "Finance projection" in body
    assert "Staff-facing financial projection is blocked" in body
    assert "Read-only auditor view" in body
    assert "Start review" not in body
    assert "Commit balance rebuild" not in body


def test_finance_admin_issue_post_routes_are_admin_only(
    app,
    staff_client,
    auditor_client,
):
    with app.app_context():
        issue_ulid = _seed_issue()

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(auditor_client, path)

    resp = auditor_client.post(
        f"/finance/admin/issues/{issue_ulid}/start-review",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    csrf = _csrf(staff_client, path)
    resp = staff_client.post(
        f"/finance/admin/issues/{issue_ulid}/start-review",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_finance_admin_can_start_review_and_close_issue(app, admin_client):
    with app.app_context():
        issue_ulid = _seed_issue()

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(admin_client, path)

    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/start-review",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    csrf = _csrf(admin_client, path)
    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/close",
        data={
            "csrf_token": csrf,
            "issue_status": "resolved",
            "close_reason": "resolved_by_route_test",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        row = db.session.get(FinanceAdminIssue, issue_ulid)
        assert row is not None
        assert row.issue_status == "resolved"
        assert row.close_reason == "resolved_by_route_test"


def test_finance_admin_can_run_integrity_sweep(app, admin_client):
    with app.app_context():
        period_key = _unused_test_period(start_year=2400)
        _seed_balance_projection_drift_only(period_key)

    csrf = _csrf(admin_client, "/finance/admin/issues")
    resp = admin_client.post(
        "/finance/admin/issues/run-sweep",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        latest = latest_finance_sweep_run()
        assert latest is not None

        balance_outcome = next(
            item
            for item in latest.summary["outcomes"]
            if item["reason_code"] == BALANCE_PROJECTION_DRIFT_REASON
            and item["ok"] is False
        )

        issue = db.session.get(
            FinanceAdminIssue,
            balance_outcome["issue_ulid"],
        )
        assert issue is not None
        assert issue.issue_status == "open"

        quarantine = db.session.get(
            FinanceQuarantine,
            balance_outcome["quarantine_ulid"],
        )
        assert quarantine is not None
        assert quarantine.source_issue_ulid == issue.ulid
        assert quarantine.reason_code == BALANCE_PROJECTION_DRIFT_REASON


def test_finance_auditor_cannot_run_integrity_sweep(
    app,
    auditor_client,
):
    with app.app_context():
        period_key = _unused_test_period(start_year=2450)
        _seed_balance_projection_drift_only(period_key)

    csrf = _csrf(auditor_client, "/finance/admin/issues")
    resp = auditor_client.post(
        "/finance/admin/issues/run-sweep",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_finance_admin_can_preview_and_commit_balance_rebuild(
    app,
    admin_client,
):
    with app.app_context():
        period_key = _unused_test_period()
        issue_ulid = _seed_balance_projection_issue(period_key=period_key)

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(admin_client, path)

    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/balance-preview",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.preview_json["kind"] == (
            "balance_projection_rebuild_preview"
        )
        assert issue.preview_json["rows_updated"] == 1

    csrf = _csrf(admin_client, path)
    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/balance-rebuild",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "resolved"
        assert issue.source_status == "closed"
        assert issue.close_reason == "balance_projection_rebuilt"
        assert issue.resolution_json["rescan_ok"] is True

        row = (
            db.session.query(BalanceMonthly)
            .filter(BalanceMonthly.period_key == period_key)
            .filter(BalanceMonthly.account_code == "1000")
            .filter(BalanceMonthly.fund_code == "unrestricted")
            .one()
        )
        assert row.net_cents == 1900


def test_finance_auditor_cannot_preview_or_commit_balance_rebuild(
    app,
    auditor_client,
):
    with app.app_context():
        period_key = _unused_test_period()
        issue_ulid = _seed_balance_projection_issue(period_key=period_key)

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(auditor_client, path)

    resp = auditor_client.post(
        f"/finance/admin/issues/{issue_ulid}/balance-preview",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    csrf = _csrf(auditor_client, path)
    resp = auditor_client.post(
        f"/finance/admin/issues/{issue_ulid}/balance-rebuild",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_finance_admin_can_mark_journal_manual_review(app, admin_client):
    with app.app_context():
        issue_ulid = _seed_journal_issue_with_quarantine()

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(admin_client, path)

    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/journal-manual-review",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "in_review"
        assert issue.source_status == "open"
        assert issue.resolution_json["recommended_path"] == (
            "manual_accounting_review"
        )

        quarantine = (
            db.session.query(FinanceQuarantine)
            .filter(FinanceQuarantine.source_issue_ulid == issue_ulid)
            .filter(FinanceQuarantine.status == STATUS_ACTIVE)
            .one_or_none()
        )
        assert quarantine is not None


def test_finance_admin_can_close_journal_after_clean_rescan(
    app,
    admin_client,
):
    with app.app_context():
        issue_ulid = _seed_journal_issue_with_quarantine()

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(admin_client, path)

    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/journal-close-clean",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "resolved"
        assert issue.source_status == "closed"
        assert issue.close_reason == "journal_integrity_clean_rescan"
        assert issue.resolution_json["rescan_ok"] is True

        quarantine = (
            db.session.query(FinanceQuarantine)
            .filter(FinanceQuarantine.source_issue_ulid == issue_ulid)
            .one_or_none()
        )
        assert quarantine is not None
        assert quarantine.status == STATUS_RELEASED


def test_finance_auditor_cannot_run_journal_resolution_routes(
    app,
    auditor_client,
):
    with app.app_context():
        issue_ulid = _seed_journal_issue_with_quarantine()

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(auditor_client, path)

    resp = auditor_client.post(
        f"/finance/admin/issues/{issue_ulid}/journal-manual-review",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    csrf = _csrf(auditor_client, path)
    resp = auditor_client.post(
        f"/finance/admin/issues/{issue_ulid}/journal-close-clean",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_finance_admin_can_preview_and_commit_posting_fact_repair(
    app,
    admin_client,
):
    with app.app_context():
        period_key = _unused_test_period(start_year=2500)
        issue_ulid, fact_ulid, expected_key = _seed_posting_fact_issue(
            period_key
        )

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(admin_client, path)

    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/posting-fact-preview",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.reason_code == POSTING_FACT_DRIFT_REASON
        assert issue.preview_json["kind"] == (
            "posting_fact_drift_repair_preview"
        )
        assert issue.preview_json["repairable_count"] == 1
        assert issue.preview_json["manual_review_count"] == 0

    csrf = _csrf(admin_client, path)
    resp = admin_client.post(
        f"/finance/admin/issues/{issue_ulid}/posting-fact-repair",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        fact = db.session.get(FinancePostingFact, fact_ulid)
        assert fact is not None
        assert fact.amount_cents == 2750
        assert fact.idempotency_key == expected_key

        issue = db.session.get(FinanceAdminIssue, issue_ulid)
        assert issue is not None
        assert issue.issue_status == "resolved"
        assert issue.source_status == "closed"
        assert issue.close_reason == "posting_fact_repaired"
        assert issue.resolution_json["rescan_ok"] is True


def test_finance_auditor_cannot_preview_or_commit_posting_fact_repair(
    app,
    auditor_client,
):
    with app.app_context():
        period_key = _unused_test_period(start_year=2550)
        issue_ulid, _fact_ulid, _expected_key = _seed_posting_fact_issue(
            period_key
        )

    path = f"/finance/admin/issues/{issue_ulid}"
    csrf = _csrf(auditor_client, path)

    resp = auditor_client.post(
        f"/finance/admin/issues/{issue_ulid}/posting-fact-preview",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    csrf = _csrf(auditor_client, path)
    resp = auditor_client.post(
        f"/finance/admin/issues/{issue_ulid}/posting-fact-repair",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403
