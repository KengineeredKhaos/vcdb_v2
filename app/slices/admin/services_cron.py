# app/slices/admin/services_cron.py

from __future__ import annotations

from sqlalchemy import select

from app.extensions import db

from .mapper import to_cron_job_status, to_cron_page
from .models import CronRun
from .registry_cron import list_jobs

STATUS_DISPLAY_ORDER = {
    "blocked": 0,
    "failed": 1,
    "running": 2,
    "succeeded": 3,
    "unknown": 4,
}


def _latest_runs(*, status: str | None = None) -> dict[str, CronRun]:
    stmt = select(CronRun)

    if status is not None:
        stmt = stmt.where(CronRun.status == status)

    rows = db.session.execute(
        stmt.order_by(CronRun.started_at_utc.desc())
    ).scalars()

    latest: dict[str, CronRun] = {}
    for row in rows:
        latest.setdefault(row.job_key, row)
    return latest


def get_cron_page():
    latest_any = _latest_runs()
    latest_success = _latest_runs(status="succeeded")
    latest_failure = _latest_runs(status="failed")

    jobs = []
    for job in list_jobs():
        current_row = latest_any.get(job.job_key)
        success_row = latest_success.get(job.job_key)
        failure_row = latest_failure.get(job.job_key)

        status = current_row.status if current_row is not None else "unknown"

        note = job.purpose
        if current_row is not None and current_row.summary:
            note = current_row.summary

        jobs.append(
            to_cron_job_status(
                job_key=job.job_key,
                label=job.label,
                status=status,
                last_success_utc=(
                    success_row.finished_at_utc
                    if success_row is not None
                    else None
                ),
                last_failure_utc=(
                    failure_row.finished_at_utc
                    if failure_row is not None
                    else None
                ),
                stale=False,
                note=note,
            )
        )

    jobs_tuple = tuple(
        sorted(
            jobs,
            key=lambda item: (
                STATUS_DISPLAY_ORDER.get(item.status, 99),
                item.job_key,
            ),
        )
    )

    return to_cron_page(
        title="Cron and Maintenance Supervision",
        summary=(
            "Admin supervises recurring jobs, failure escalation, and "
            "manual follow-up. Owning code stays in slice-local runners."
        ),
        jobs=jobs_tuple,
    )
