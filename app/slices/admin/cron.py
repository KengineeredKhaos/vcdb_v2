# app/slices/admin/cron.py
from __future__ import annotations
from app.extensions import db
from app.lib.chrono import utc_now  # -> ISO-8601 Z string
from app.slices.admin.models import CronStatus


def cron_mark_success(job_name: str) -> None:
    row = db.session.get(CronStatus, job_name) or CronStatus(
        job_name=job_name
    )
    row.last_success_utc = utc_now()
    row.last_error_utc = None
    row.last_error = None
    db.session.add(row)
    db.session.commit()


def cron_mark_failure(job_name: str, err_msg: str) -> None:
    row = db.session.get(CronStatus, job_name) or CronStatus(
        job_name=job_name
    )
    row.last_error_utc = utc_now()
    row.last_error = (err_msg or "")[:2000]
    db.session.add(row)
    db.session.commit()
