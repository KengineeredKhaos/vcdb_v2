from __future__ import annotations

import sqlite3
from pathlib import Path

from app.slices.admin.jobs_backup import run_backup_daily


def _make_sqlite_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("create table if not exists demo (id integer primary key)")
        conn.execute("insert into demo default values")
        conn.commit()


def test_run_backup_daily_local_only(app, tmp_path):
    db_file = tmp_path / "app.sqlite3"
    _make_sqlite_db(db_file)

    with app.app_context():
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
        app.config["CRON_BACKUP_LOCAL_ROOT"] = str(tmp_path / "backups")
        app.config["CRON_BACKUP_EXTERNAL_ROOT"] = None
        app.config["CRON_BACKUP_REQUIRE_EXTERNAL"] = False

        summary = run_backup_daily(unit_key="2026-03-30")

    backup_copy = tmp_path / "backups" / "2026-03-30" / (
        "vcdb-backup--2026-03-30.sqlite3"
    )
    manifest = tmp_path / "backups" / "2026-03-30" / "MANIFEST.json"

    assert backup_copy.exists()
    assert manifest.exists()
    assert "Local backup completed" in summary
