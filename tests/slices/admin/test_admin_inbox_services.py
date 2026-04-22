# tests/slices/admin/test_admin_inbox_services.py

from __future__ import annotations

from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts.admin_v2 import (
    AdminAlertCloseDTO,
    AdminAlertUpsertDTO,
    AdminResolutionTargetDTO,
)
from app.slices.admin import services as svc
from app.slices.admin.models import AdminAlert, AdminAlertArchive


def _clear_admin_inbox_tables() -> None:
    db.session.query(AdminAlertArchive).delete()
    db.session.query(AdminAlert).delete()
    db.session.commit()


def _upsert_dto(
    *,
    request_id: str = "req-resource-org-validation-001",
    title: str = "Resource org validation required",
    summary: str = "Admin review is required.",
):
    return AdminAlertUpsertDTO(
        source_slice="resources",
        reason_code="advisory_resources_org_validation",
        request_id=request_id,
        target_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAB",
        title=title,
        summary=summary,
        source_status="pending_review",
        workflow_key="resource_org_validation",
        resolution_target=AdminResolutionTargetDTO(
            route_name="resources.admin_issue_org_validation_get",
            route_params={"request_id": request_id},
            launch_label="Open resource org validation issue",
        ),
        context={"resource_name": "Example Resource"},
    )


def test_upsert_inbox_item_creates_hot_row(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        dto = _upsert_dto()
        receipt = svc.upsert_alert(dto)
        db.session.commit()

        row = db.session.execute(
            select(AdminAlert).where(AdminAlert.ulid == receipt.alert_ulid)
        ).scalar_one()

        assert row.source_slice == "resources"
        assert row.reason_code == "advisory_resources_org_validation"
        assert row.request_id == dto.request_id
        assert row.admin_status == svc.ADMIN_STATUS_OPEN
        assert row.title == dto.title
        assert row.summary == dto.summary
        assert row.dedupe_key == (
            "resources:advisory_resources_org_validation:req-resource-org-validation-001:01ARZ3NDEKTSV4RRFFQ69G5FAB"
        )


def test_upsert_inbox_item_updates_existing_row_by_dedupe_key(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        first = svc.upsert_alert(_upsert_dto())
        db.session.commit()

        second = svc.upsert_alert(
            _upsert_dto(
                title="Updated validation title",
                summary="Updated summary text.",
            )
        )
        db.session.commit()

        rows = db.session.execute(select(AdminAlert)).scalars().all()

        assert len(rows) == 1
        assert first.alert_ulid == second.alert_ulid
        assert rows[0].title == "Updated validation title"
        assert rows[0].summary == "Updated summary text."


def test_acknowledge_inbox_item_marks_queue_state(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        receipt = svc.upsert_alert(_upsert_dto())
        db.session.commit()

        updated = svc.acknowledge_alert(
            receipt.alert_ulid,
            actor_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAC",
        )
        db.session.commit()

        row = db.session.execute(
            select(AdminAlert).where(AdminAlert.ulid == updated.alert_ulid)
        ).scalar_one()

        assert row.admin_status == svc.ADMIN_STATUS_ACKNOWLEDGED
        assert row.acknowledged_by_ulid == "01ARZ3NDEKTSV4RRFFQ69G5FAC"
        assert row.acknowledged_at_utc is not None


def test_close_inbox_item_marks_terminal_status(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        svc.upsert_alert(_upsert_dto())
        db.session.commit()

        receipt = svc.close_alert(
            AdminAlertCloseDTO(
                source_slice="resources",
                reason_code="advisory_resources_org_validation",
                request_id="req-resource-org-validation-001",
                target_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAB",
                source_status="resolved",
                close_reason="approved_in_source_slice",
                admin_status=svc.ADMIN_STATUS_RESOLVED,
            )
        )
        db.session.commit()

        assert receipt is not None

        row = db.session.execute(
            select(AdminAlert).where(
                AdminAlert.request_id == "req-resource-org-validation-001"
            )
        ).scalar_one()

        assert row.admin_status == svc.ADMIN_STATUS_RESOLVED
        assert row.source_status == "resolved"
        assert row.close_reason == "approved_in_source_slice"
        assert row.closed_at_utc is not None


def test_archive_terminal_items_moves_row_to_archive(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        svc.upsert_alert(_upsert_dto())
        db.session.commit()

        svc.close_alert(
            AdminAlertCloseDTO(
                source_slice="resources",
                reason_code="advisory_resources_org_validation",
                request_id="req-resource-org-validation-001",
                target_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAB",
                source_status="resolved",
                close_reason="approved_in_source_slice",
                admin_status=svc.ADMIN_STATUS_RESOLVED,
            )
        )
        db.session.commit()

        moved = svc.archive_terminal_alerts()
        db.session.commit()

        hot_rows = db.session.execute(select(AdminAlert)).scalars().all()
        archive_rows = (
            db.session.execute(select(AdminAlertArchive)).scalars().all()
        )

        assert moved == 1
        assert hot_rows == []
        assert len(archive_rows) == 1
        assert archive_rows[0].source_slice == "resources"
        assert (
            archive_rows[0].reason_code == "advisory_resources_org_validation"
        )
        assert archive_rows[0].archive_reason == "cron_cycle"
        assert archive_rows[0].original_alert_ulid is not None


def test_list_active_inbox_items_only_returns_active_statuses(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        svc.upsert_alert(_upsert_dto())
        db.session.commit()

        svc.upsert_alert(
            _upsert_dto(
                request_id="req-sponsor-sla-review-001",
                title="Sponsor SLA review required",
                summary="Second active item.",
            )
        )
        db.session.commit()

        svc.close_alert(
            AdminAlertCloseDTO(
                source_slice="resources",
                reason_code="advisory_resources_org_validation",
                request_id="req-resource-org-validation-001",
                target_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAB",
                source_status="resolved",
                close_reason="approved_in_source_slice",
                admin_status=svc.ADMIN_STATUS_RESOLVED,
            )
        )
        db.session.commit()

        items = svc.list_active_alerts()

        assert len(items) == 1
        assert items[0].summary == "Second active item."
        assert items[0].status in svc.ACTIVE_ADMIN_STATUSES
        assert items[0].reason_code == "advisory_resources_org_validation"
