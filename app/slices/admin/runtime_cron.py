from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from socket import gethostname
from typing import Protocol

from sqlalchemy import delete, func, select

from app.extensions import db
from app.lib.chrono import now_iso8601_ms, to_iso8601, utcnow_aware
from app.lib.ids import new_ulid

from .models import CronLock, CronRun

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"

TRIGGER_SYSTEM = "system"
TRIGGER_RETRY = "retry"
TRIGGER_MANUAL = "manual"

MAX_AUTOMATIC_ATTEMPTS = 2


class CronRunner(Protocol):
    def __call__(self, *, unit_key: str) -> str:
        ...


@dataclass(frozen=True)
class CronExecutionResult:
    job_key: str
    unit_key: str
    status: str
    attempt_no: int
    summary: str
    admin_flagged: bool = False
    run_ulid: str | None = None
    error_text: str | None = None


@dataclass(frozen=True)
class CronJobDef:
    job_key: str
    label: str
    owner_slice: str
    cadence_note: str
    purpose: str
    critical: bool
    lock_ttl_seconds: int
    unit_key_factory: Callable[[], str]
    runner: CronRunner


def _now() -> str:
    return now_iso8601_ms()


def _lock_key(job_key: str, unit_key: str) -> str:
    return f"{job_key}:{unit_key}"


def _latest_attempt_no(job_key: str, unit_key: str) -> int:
    stmt = select(func.max(CronRun.attempt_no)).where(
        CronRun.job_key == job_key,
        CronRun.unit_key == unit_key,
    )
    return int(db.session.execute(stmt).scalar() or 0)


def _already_succeeded(job_key: str, unit_key: str) -> bool:
    stmt = select(CronRun.ulid).where(
        CronRun.job_key == job_key,
        CronRun.unit_key == unit_key,
        CronRun.status == STATUS_SUCCEEDED,
    )
    return db.session.execute(stmt).scalar_one_or_none() is not None


def _delete_expired_lock(lock_key: str, now_utc: str) -> None:
    stmt = delete(CronLock).where(
        CronLock.lock_key == lock_key,
        CronLock.expires_at_utc < now_utc,
    )
    db.session.execute(stmt)
    db.session.flush()


def _acquire_lock(
    *,
    job_key: str,
    unit_key: str,
    owner_run_ulid: str,
    ttl_seconds: int,
) -> bool:
    now_dt = utcnow_aware()
    now_utc = to_iso8601(now_dt)

    key = _lock_key(job_key, unit_key)
    _delete_expired_lock(key, now_utc)

    existing = db.session.get(CronLock, key)
    if existing is not None:
        return False

    expires_utc = to_iso8601(now_dt + timedelta(seconds=int(ttl_seconds)))

    lock = CronLock(
        lock_key=key,
        job_key=job_key,
        unit_key=unit_key,
        owner_run_ulid=owner_run_ulid,
        acquired_at_utc=now_utc,
        expires_at_utc=expires_utc,
    )
    db.session.add(lock)
    db.session.flush()
    return True


def _release_lock(job_key: str, unit_key: str) -> None:
    db.session.execute(
        delete(CronLock).where(
            CronLock.lock_key == _lock_key(job_key, unit_key)
        )
    )
    db.session.flush()


def _create_run(
    *,
    job_key: str,
    unit_key: str,
    attempt_no: int,
    trigger_mode: str,
    actor_ulid: str | None,
) -> CronRun:
    request_id = f"cron:{job_key}:{unit_key}:attempt:{attempt_no}"
    row = CronRun(
        ulid=new_ulid(),
        job_key=job_key,
        unit_key=unit_key,
        status=STATUS_RUNNING,
        attempt_no=attempt_no,
        started_at_utc=_now(),
        finished_at_utc=None,
        summary="Run started.",
        error_text=None,
        request_id=request_id,
        actor_ulid=actor_ulid,
        trigger_mode=trigger_mode,
        host_name=gethostname(),
    )
    db.session.add(row)
    db.session.flush()
    return row


def _flag_second_failure(
    *,
    job_key: str,
    unit_key: str,
    run_ulid: str,
    error_text: str,
) -> None:
    from app.extensions.contracts.admin_v2 import (
        AdminAlertUpsertDTO,
        AdminResolutionTargetDTO,
        upsert_alert,
    )

    request_id = f"cron:{job_key}:{unit_key}:run:{run_ulid}"

    dto = AdminAlertUpsertDTO(
        source_slice="admin",
        reason_code="failed_admin_cron_second_failure",
        request_id=request_id,
        target_ulid=None,
        title=f"Cron failure: {job_key}",
        summary=(
            f"Job {job_key} failed twice for unit {unit_key}. "
            f"Latest error: {error_text}"
        ),
        source_status="failed",
        workflow_key="admin_cron_issue",
        resolution_target=AdminResolutionTargetDTO(
            route_name="admin.cron",
            route_params={},
            launch_label="Open cron supervision",
        ),
        context={
            "job_key": job_key,
            "unit_key": unit_key,
            "run_ulid": run_ulid,
            "latest_error": error_text,
        },
    )
    upsert_alert(dto)


def execute_job(
    *,
    job: CronJobDef,
    unit_key: str,
    trigger_mode: str = TRIGGER_SYSTEM,
    actor_ulid: str | None = None,
) -> CronExecutionResult:
    if _already_succeeded(job.job_key, unit_key):
        return CronExecutionResult(
            job_key=job.job_key,
            unit_key=unit_key,
            status=STATUS_SKIPPED,
            attempt_no=_latest_attempt_no(job.job_key, unit_key),
            summary="Unit already succeeded; no-op.",
        )

    latest_attempt = _latest_attempt_no(job.job_key, unit_key)
    if latest_attempt >= MAX_AUTOMATIC_ATTEMPTS:
        return CronExecutionResult(
            job_key=job.job_key,
            unit_key=unit_key,
            status=STATUS_BLOCKED,
            attempt_no=latest_attempt,
            summary="Automatic retry budget exhausted; Admin review required.",
        )

    owner_run_ulid = new_ulid()
    if not _acquire_lock(
        job_key=job.job_key,
        unit_key=unit_key,
        owner_run_ulid=owner_run_ulid,
        ttl_seconds=job.lock_ttl_seconds,
    ):
        return CronExecutionResult(
            job_key=job.job_key,
            unit_key=unit_key,
            status=STATUS_BLOCKED,
            attempt_no=latest_attempt,
            summary="Another run is active for this unit.",
        )

    last_result: CronExecutionResult | None = None
    try:
        for attempt_no in range(
            latest_attempt + 1, MAX_AUTOMATIC_ATTEMPTS + 1
        ):
            run = _create_run(
                job_key=job.job_key,
                unit_key=unit_key,
                attempt_no=attempt_no,
                trigger_mode=trigger_mode,
                actor_ulid=actor_ulid,
            )
            try:
                summary = job.runner(unit_key=unit_key)
            except Exception as exc:  # noqa: BLE001
                run.status = STATUS_FAILED
                run.finished_at_utc = _now()
                run.summary = "Run failed."
                run.error_text = str(exc)
                db.session.flush()

                admin_flagged = attempt_no >= MAX_AUTOMATIC_ATTEMPTS
                if admin_flagged:
                    _flag_second_failure(
                        job_key=job.job_key,
                        unit_key=unit_key,
                        run_ulid=run.ulid,
                        error_text=str(exc),
                    )

                last_result = CronExecutionResult(
                    job_key=job.job_key,
                    unit_key=unit_key,
                    status=STATUS_FAILED,
                    attempt_no=attempt_no,
                    summary=run.summary,
                    admin_flagged=admin_flagged,
                    run_ulid=run.ulid,
                    error_text=str(exc),
                )
                if admin_flagged:
                    break
                continue

            run.status = STATUS_SUCCEEDED
            run.finished_at_utc = _now()
            run.summary = summary
            run.error_text = None
            db.session.flush()

            last_result = CronExecutionResult(
                job_key=job.job_key,
                unit_key=unit_key,
                status=STATUS_SUCCEEDED,
                attempt_no=attempt_no,
                summary=summary,
                run_ulid=run.ulid,
            )
            break
    finally:
        _release_lock(job.job_key, unit_key)

    assert last_result is not None
    return last_result
