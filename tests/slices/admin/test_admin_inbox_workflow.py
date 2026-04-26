# tests/slices/admin/test_admin_inbox_workflow.py

from __future__ import annotations

import pytest

from app.extensions import db
from app.extensions.contracts.admin_v2 import (
    AdminAlertUpsertDTO,
    AdminResolutionTargetDTO,
)
from app.lib.ids import new_ulid
from app.slices.admin import services as admin_svc
from app.slices.admin.models import AdminAlert, AdminAlertArchive


@pytest.fixture
def anon_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


@pytest.fixture
def admin_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()
    client.environ_base.update({"HTTP_X_AUTH_STUB": "admin"})
    return client


@pytest.fixture
def staff_client(app):
    app.config["AUTH_MODE"] = "stub"
    app.config["ALLOW_HEADER_AUTH"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()
    client.environ_base.update({"HTTP_X_AUTH_STUB": "staff"})
    return client


@pytest.fixture(autouse=True)
def _clear_admin_inbox_tables(app):
    with app.app_context():
        db.session.query(AdminAlertArchive).delete()
        db.session.query(AdminAlert).delete()
        db.session.commit()
    yield


def _create_alert(
    *,
    source_slice: str,
    reason_code: str,
    launch_label: str,
    source_status: str = "pending_review",
    target_ulid: str | None = None,
    request_id: str | None = None,
) -> str:
    rid = request_id or new_ulid()
    target = target_ulid or new_ulid()

    receipt = admin_svc.upsert_alert(
        AdminAlertUpsertDTO(
            source_slice=source_slice,
            reason_code=reason_code,
            request_id=rid,
            target_ulid=target,
            title=f"{reason_code} title {rid}",
            summary=f"{reason_code} summary {rid}",
            source_status=source_status,
            workflow_key=f"{source_slice}_{reason_code}_issue",
            resolution_target=AdminResolutionTargetDTO(
                route_name="admin.index",
                route_params={},
                launch_label=launch_label,
            ),
            context={
                "target_ulid": target,
                "reason_code": reason_code,
            },
        )
    )
    db.session.commit()
    return receipt.alert_ulid


def _alert(alert_ulid: str):
    row = admin_svc.get_alert_by_ulid(alert_ulid)
    assert row is not None
    return row


def test_admin_inbox_active_renders_launch_action(admin_client, app):
    with app.app_context():
        alert_ulid = _create_alert(
            source_slice="resources",
            reason_code="advisory_resources_onboard",
            launch_label="Open workflow test issue",
        )
        row = _alert(alert_ulid)
        assert row.admin_status == "open"

    resp = admin_client.get("/admin/inbox/")
    assert resp.status_code == 200
    assert b"Unified Admin Inbox" in resp.data
    assert b"Open workflow test issue" in resp.data
    assert b"advisory_resources_onboard" in resp.data


def test_admin_inbox_button_visibility_matches_alert_type(
    admin_client,
    app,
):
    with app.app_context():
        _create_alert(
            source_slice="resources",
            reason_code="advisory_resources_onboard",
            launch_label="Open onboarding review issue",
        )
        _create_alert(
            source_slice="customers",
            reason_code="advisory_customers_assessment_completed",
            launch_label="Open assessment info issue",
        )

    resp = admin_client.get("/admin/inbox/")
    assert resp.status_code == 200
    body = resp.data

    assert b"Open onboarding review issue" in body
    assert b"Open assessment info issue" in body
    assert b"Dismiss as info-only" in body


def test_admin_inbox_acknowledge_changes_status_only(admin_client, app):
    with app.app_context():
        alert_ulid = _create_alert(
            source_slice="sponsors",
            reason_code="advisory_sponsors_onboard",
            launch_label="Open acknowledge issue",
        )
        before = _alert(alert_ulid)
        assert before.source_status == "pending_review"
        assert before.admin_status == "open"

    resp = admin_client.post(
        f"/admin/inbox/{alert_ulid}/acknowledge",
        data={"view": "active"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        row = _alert(alert_ulid)
        assert row.admin_status == "acknowledged"
        assert row.source_status == "pending_review"
        assert row.acknowledged_by_ulid
        assert row.acknowledged_at_utc


def test_admin_inbox_start_review_changes_status_only(
    admin_client,
    app,
):
    with app.app_context():
        alert_ulid = _create_alert(
            source_slice="customers",
            reason_code="advisory_customers_watchlist",
            launch_label="Open start review issue",
        )
        before = _alert(alert_ulid)
        assert before.admin_status == "open"
        assert before.source_status == "pending_review"

    resp = admin_client.post(
        f"/admin/inbox/{alert_ulid}/start-review",
        data={"view": "active"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        row = _alert(alert_ulid)
        assert row.admin_status == "in_review"
        assert row.source_status == "pending_review"


def test_admin_inbox_snooze_and_unsnooze_move_between_views(
    admin_client,
    app,
):
    launch_label = f"Open snooze workflow issue {new_ulid()}"

    with app.app_context():
        alert_ulid = _create_alert(
            source_slice="resources",
            reason_code="advisory_resources_onboard",
            launch_label=launch_label,
        )

    resp = admin_client.post(
        f"/admin/inbox/{alert_ulid}/snooze",
        data={"view": "active"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        row = _alert(alert_ulid)
        assert row.admin_status == "snoozed"
        assert row.source_status == "pending_review"

    active_resp = admin_client.get("/admin/inbox/")
    assert active_resp.status_code == 200
    assert launch_label.encode() not in active_resp.data

    snoozed_resp = admin_client.get("/admin/inbox/?view=snoozed")
    assert snoozed_resp.status_code == 200
    assert launch_label.encode() in snoozed_resp.data

    resp = admin_client.post(
        f"/admin/inbox/{alert_ulid}/unsnooze",
        data={"view": "snoozed"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        row = _alert(alert_ulid)
        assert row.admin_status == "open"
        assert row.source_status == "pending_review"

    active_resp = admin_client.get("/admin/inbox/")
    assert active_resp.status_code == 200
    assert launch_label.encode() in active_resp.data


def test_admin_inbox_dismiss_moves_info_alert_to_closed(
    admin_client,
    app,
):
    launch_label = f"Open dismissible issue {new_ulid()}"

    with app.app_context():
        alert_ulid = _create_alert(
            source_slice="customers",
            reason_code="advisory_customers_assessment_completed",
            launch_label=launch_label,
        )

    resp = admin_client.post(
        f"/admin/inbox/{alert_ulid}/dismiss",
        data={"view": "active"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        row = _alert(alert_ulid)
        assert row.admin_status == "dismissed"
        assert row.source_status == "pending_review"
        assert row.close_reason == "admin_dismissed"
        assert row.closed_at_utc

    active_resp = admin_client.get("/admin/inbox/")
    assert active_resp.status_code == 200
    assert launch_label.encode() not in active_resp.data

    closed_resp = admin_client.get("/admin/inbox/?view=closed")
    assert closed_resp.status_code == 200
    assert launch_label.encode() in closed_resp.data


def test_admin_inbox_mark_duplicate_records_link_and_closes(
    admin_client,
    app,
):
    with app.app_context():
        original_ulid = _create_alert(
            source_slice="resources",
            reason_code="advisory_resources_onboard",
            launch_label=f"Open original duplicate seed {new_ulid()}",
        )
        duplicate_ulid = _create_alert(
            source_slice="resources",
            reason_code="advisory_resources_onboard",
            launch_label=f"Open duplicate test issue {new_ulid()}",
        )

    resp = admin_client.post(
        f"/admin/inbox/{duplicate_ulid}/mark-duplicate",
        data={
            "view": "active",
            "duplicate_of_alert_ulid": original_ulid,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        row = _alert(duplicate_ulid)
        assert row.admin_status == "duplicate"
        assert row.source_status == "pending_review"
        assert row.close_reason == "admin_duplicate"
        assert row.duplicate_of_alert_ulid == original_ulid

    closed_resp = admin_client.get("/admin/inbox/?view=closed")
    assert closed_resp.status_code == 200
    assert b"Open duplicate test issue" in closed_resp.data


def test_admin_inbox_triage_post_denies_staff(staff_client, app):
    with app.app_context():
        alert_ulid = _create_alert(
            source_slice="customers",
            reason_code="advisory_customers_watchlist",
            launch_label="Open denied triage issue",
        )

    resp = staff_client.post(
        f"/admin/inbox/{alert_ulid}/acknowledge",
        data={"view": "active"},
        follow_redirects=False,
    )
    assert resp.status_code in {302, 401, 403}


def test_admin_inbox_timed_history_stays_out_of_active(admin_client, app):
    launch_label = f"Open archive posture issue {new_ulid()}"

    with app.app_context():
        alert_ulid = _create_alert(
            source_slice="customers",
            reason_code="advisory_customers_assessment_completed",
            launch_label=launch_label,
        )
        admin_svc.dismiss_alert(
            alert_ulid,
            actor_ulid="stub:admin",
        )
        db.session.commit()

    active_resp = admin_client.get("/admin/inbox/")
    assert active_resp.status_code == 200
    assert launch_label.encode() not in active_resp.data

    closed_resp = admin_client.get("/admin/inbox/?view=closed")
    assert closed_resp.status_code == 200
    assert launch_label.encode() in closed_resp.data
