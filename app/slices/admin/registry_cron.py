from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app

from .jobs_backup import run_backup_daily
from .runtime_cron import CronJobDef


def _cron_tz() -> ZoneInfo:
    tz_name = current_app.config.get(
        "CRON_TIMEZONE",
        "America/Los_Angeles",
    )
    return ZoneInfo(str(tz_name))


def _today_unit_key() -> str:
    return datetime.now(_cron_tz()).date().isoformat()


REGISTRY: dict[str, CronJobDef] = {
    "backup.daily": CronJobDef(
        job_key="backup.daily",
        label="Daily database backup",
        owner_slice="admin",
        cadence_note="Daily during off-duty hours.",
        purpose=(
            "Create a deterministic database backup, write a local "
            "manifest, and copy to external storage when configured."
        ),
        critical=True,
        lock_ttl_seconds=60 * 60,
        unit_key_factory=_today_unit_key,
        runner=run_backup_daily,
    ),
}


def get_job(job_key: str) -> CronJobDef:
    try:
        return REGISTRY[job_key]
    except KeyError as exc:  # pragma: no cover - tiny helper
        raise KeyError(f"Unknown cron job: {job_key}") from exc


def list_jobs() -> tuple[CronJobDef, ...]:
    return tuple(REGISTRY.values())
