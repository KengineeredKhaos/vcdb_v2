from __future__ import annotations

from app.extensions import db
from app.slices.admin.models import CronRun
from app.slices.admin.services_cron import get_cron_page


def _clear_cron_tables() -> None:
    db.session.query(CronRun).delete()
    db.session.commit()


def test_get_cron_page_includes_registry_job(app):
    with app.app_context():
        _clear_cron_tables()
        row = CronRun(
            ulid="01TESTCRONRUN00000000000000",
            job_key="backup.daily",
            unit_key="2099-03-30-services-page",
            status="succeeded",
            attempt_no=99,
            started_at_utc="2099-03-30T01:00:00Z",
            finished_at_utc="2099-03-30T01:01:00Z",
            summary="Local and external backup completed.",
            error_text=None,
            request_id=None,
            actor_ulid=None,
            trigger_mode="system",
            host_name="test-host",
        )
        db.session.add(row)
        db.session.commit()

        page = get_cron_page()

    assert page.jobs
    assert page.jobs[0].job_key == "backup.daily"
    assert page.jobs[0].status == "succeeded"
