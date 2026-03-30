from __future__ import annotations

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.slices.admin.registry_cron import get_job, list_jobs
from app.slices.admin.runtime_cron import (
    TRIGGER_MANUAL,
    TRIGGER_RETRY,
    TRIGGER_SYSTEM,
    execute_job,
)


@click.group("cron")
def cron_group() -> None:
    """Run and inspect VCDB cron jobs."""


@cron_group.command("list")
@with_appcontext
def list_command() -> None:
    for job in list_jobs():
        click.echo(f"{job.job_key}: {job.label}")


@cron_group.command("run")
@click.argument("job_key")
@click.option("--unit-key", default=None)
@click.option(
    "--trigger-mode",
    type=click.Choice([TRIGGER_SYSTEM, TRIGGER_RETRY, TRIGGER_MANUAL]),
    default=TRIGGER_SYSTEM,
    show_default=True,
)
@with_appcontext
def run_command(
    job_key: str, unit_key: str | None, trigger_mode: str
) -> None:
    job = get_job(job_key)
    resolved_unit = unit_key or job.unit_key_factory()
    try:
        result = execute_job(
            job=job,
            unit_key=resolved_unit,
            trigger_mode=trigger_mode,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    click.echo(
        f"{result.job_key} [{result.unit_key}] -> {result.status} "
        f"attempt={result.attempt_no}"
    )
    click.echo(result.summary)
    if result.error_text:
        click.echo(result.error_text)
