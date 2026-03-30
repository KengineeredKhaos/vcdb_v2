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


def _latest_runs() -> dict[str, CronRun]:
    rows = db.session.execute(
        select(CronRun).order_by(CronRun.started_at_utc.desc())
    ).scalars()
    latest: dict[str, CronRun] = {}
    for row in rows:
        latest.setdefault(row.job_key, row)
    return latest


def get_cron_page():
    latest = _latest_runs()
    jobs = []
    for job in list_jobs():
        row = latest.get(job.job_key)
        status = row.status if row is not None else "unknown"
        note = job.purpose
        if row is not None and row.summary:
            note = row.summary
        jobs.append(
            to_cron_job_status(
                job_key=job.job_key,
                label=job.label,
                status=status,
                last_success_utc=(
                    row.finished_at_utc
                    if row is not None and row.status == "succeeded"
                    else None
                ),
                last_failure_utc=(
                    row.finished_at_utc
                    if row is not None and row.status == "failed"
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
