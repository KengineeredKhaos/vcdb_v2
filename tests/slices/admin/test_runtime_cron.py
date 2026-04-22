from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.extensions import db
from app.slices.admin.models import CronLock, CronRun
from app.slices.admin.runtime_cron import (
    CronExecutionResult,
    CronJobDef,
    STATUS_SKIPPED,
    STATUS_SUCCEEDED,
    execute_job,
)


@dataclass
class CallCounter:
    count: int = 0

    def ok(self, *, unit_key: str) -> str:
        self.count += 1
        return f"done:{unit_key}"

    def fail(self, *, unit_key: str) -> str:
        self.count += 1
        raise RuntimeError(f"boom:{unit_key}")


def _job(runner):
    return CronJobDef(
        job_key="backup.daily",
        label="Daily database backup",
        owner_slice="admin",
        cadence_note="daily",
        purpose="test",
        critical=True,
        lock_ttl_seconds=60,
        unit_key_factory=lambda: "2026-03-30",
        runner=runner,
    )


def _reset_cron_tables() -> None:
    db.session.query(CronLock).delete()
    db.session.query(CronRun).delete()
    db.session.commit()


def test_execute_job_success_then_skip(app):
    counter = CallCounter()
    unit_key = "test-success-2026-03-30"

    with app.app_context():
        _reset_cron_tables()

        first = execute_job(job=_job(counter.ok), unit_key=unit_key)
        db.session.commit()
        second = execute_job(job=_job(counter.ok), unit_key=unit_key)

    assert first.status == STATUS_SUCCEEDED
    assert second.status == STATUS_SKIPPED
    assert counter.count == 1


def test_execute_job_second_failure_flags_admin(app):
    counter = CallCounter()
    unit_key = "test-fail-2026-03-30"

    with app.app_context():
        _reset_cron_tables()

        result = execute_job(job=_job(counter.fail), unit_key=unit_key)
        db.session.commit()

        runs = (
            db.session.query(CronRun)
            .filter_by(
                job_key="backup.daily",
                unit_key=unit_key,
            )
            .order_by(CronRun.attempt_no.asc())
            .all()
        )

    assert result.status == "failed"
    assert result.admin_flagged is True
    assert counter.count == 2
    assert [row.attempt_no for row in runs] == [1, 2]
