# tests/slices/admin/test_admin_inbox_services.py

from __future__ import annotations

from sqlalchemy import select

from app.extensions import db
from app.slices.admin import services as svc
from app.slices.admin.models import AdminInboxArchive, AdminInboxItem


def _clear_admin_inbox_tables() -> None:
    db.session.query(AdminInboxArchive).delete()
    db.session.query(AdminInboxItem).delete()
    db.session.commit()


def _upsert_dto(
    *,
    source_ref_ulid: str = "01ARZ3NDEKTSV4RRFFQ69G5FAA",
    title: str = "Resource org validation required",
    summary: str = "Admin review is required.",
):
    return svc.AdminInboxUpsertDTO(
        source_slice="resources",
        issue_kind="org_validation_required",
        source_ref_ulid=source_ref_ulid,
        subject_ref_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAB",
        severity="high",
        title=title,
        summary=summary,
        source_status="pending_review",
        workflow_key="resource_org_validation",
        resolution_route="resources.admin_review",
        context={"resource_name": "Example Resource"},
    )


def test_upsert_inbox_item_creates_hot_row(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        dto = _upsert_dto()
        receipt = svc.upsert_inbox_item(dto)
        db.session.commit()

        row = db.session.execute(
            select(AdminInboxItem).where(
                AdminInboxItem.ulid == receipt.inbox_item_ulid
            )
        ).scalar_one()

        assert row.source_slice == "resources"
        assert row.issue_kind == "org_validation_required"
        assert row.source_ref_ulid == dto.source_ref_ulid
        assert row.admin_status == svc.ADMIN_STATUS_OPEN
        assert row.title == dto.title
        assert row.summary == dto.summary
        assert row.dedupe_key == (
            "resources:org_validation_required:" "01ARZ3NDEKTSV4RRFFQ69G5FAA"
        )


def test_upsert_inbox_item_updates_existing_row_by_dedupe_key(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        first = svc.upsert_inbox_item(_upsert_dto())
        db.session.commit()

        second = svc.upsert_inbox_item(
            _upsert_dto(
                title="Updated validation title",
                summary="Updated summary text.",
            )
        )
        db.session.commit()

        rows = db.session.execute(select(AdminInboxItem)).scalars().all()

        assert len(rows) == 1
        assert first.inbox_item_ulid == second.inbox_item_ulid
        assert rows[0].title == "Updated validation title"
        assert rows[0].summary == "Updated summary text."


def test_acknowledge_inbox_item_marks_queue_state(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        receipt = svc.upsert_inbox_item(_upsert_dto())
        db.session.commit()

        updated = svc.acknowledge_inbox_item(
            receipt.inbox_item_ulid,
            actor_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAC",
        )
        db.session.commit()

        row = db.session.execute(
            select(AdminInboxItem).where(
                AdminInboxItem.ulid == updated.inbox_item_ulid
            )
        ).scalar_one()

        assert row.admin_status == svc.ADMIN_STATUS_ACKNOWLEDGED
        assert row.acknowledged_by_ulid == "01ARZ3NDEKTSV4RRFFQ69G5FAC"
        assert row.acknowledged_at_utc is not None


def test_close_inbox_item_marks_terminal_status(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        svc.upsert_inbox_item(_upsert_dto())
        db.session.commit()

        receipt = svc.close_inbox_item(
            svc.AdminInboxCloseDTO(
                source_slice="resources",
                issue_kind="org_validation_required",
                source_ref_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAA",
                source_status="resolved",
                close_reason="approved_in_source_slice",
                admin_status=svc.ADMIN_STATUS_RESOLVED,
            )
        )
        db.session.commit()

        assert receipt is not None

        row = db.session.execute(
            select(AdminInboxItem).where(
                AdminInboxItem.source_ref_ulid == "01ARZ3NDEKTSV4RRFFQ69G5FAA"
            )
        ).scalar_one()

        assert row.admin_status == svc.ADMIN_STATUS_RESOLVED
        assert row.source_status == "resolved"
        assert row.close_reason == "approved_in_source_slice"
        assert row.closed_at_utc is not None


def test_archive_terminal_items_moves_row_to_archive(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        svc.upsert_inbox_item(_upsert_dto())
        db.session.commit()

        svc.close_inbox_item(
            svc.AdminInboxCloseDTO(
                source_slice="resources",
                issue_kind="org_validation_required",
                source_ref_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAA",
                source_status="resolved",
                close_reason="approved_in_source_slice",
                admin_status=svc.ADMIN_STATUS_RESOLVED,
            )
        )
        db.session.commit()

        moved = svc.archive_terminal_items()
        db.session.commit()

        hot_rows = db.session.execute(select(AdminInboxItem)).scalars().all()
        archive_rows = (
            db.session.execute(select(AdminInboxArchive)).scalars().all()
        )

        assert moved == 1
        assert hot_rows == []
        assert len(archive_rows) == 1
        assert archive_rows[0].source_slice == "resources"
        assert archive_rows[0].issue_kind == "org_validation_required"
        assert archive_rows[0].archive_reason == "cron_cycle"
        assert archive_rows[0].original_inbox_ulid is not None


def test_list_active_inbox_items_only_returns_active_statuses(app):
    with app.app_context():
        _clear_admin_inbox_tables()

        svc.upsert_inbox_item(_upsert_dto())
        db.session.commit()

        svc.upsert_inbox_item(
            _upsert_dto(
                source_ref_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAD",
                title="Sponsor SLA review required",
                summary="Second active item.",
            )
        )
        db.session.commit()

        svc.close_inbox_item(
            svc.AdminInboxCloseDTO(
                source_slice="resources",
                issue_kind="org_validation_required",
                source_ref_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAA",
                source_status="resolved",
                close_reason="approved_in_source_slice",
                admin_status=svc.ADMIN_STATUS_RESOLVED,
            )
        )
        db.session.commit()

        items = svc.list_active_inbox_items()

        assert len(items) == 1
        assert items[0].summary == "Second active item."
        assert items[0].status in svc.ACTIVE_ADMIN_STATUSES
