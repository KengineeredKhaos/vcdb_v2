from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from flask import current_app


def _sqlite_path() -> Path:
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if not uri.startswith("sqlite:///"):
        raise RuntimeError("backup.daily currently supports sqlite only.")
    return Path(uri.removeprefix("sqlite:///"))


def _local_backup_root() -> Path:
    configured = current_app.config.get("CRON_BACKUP_LOCAL_ROOT")
    if configured:
        return Path(str(configured))
    return Path(current_app.instance_path) / "backups"


def _external_backup_root() -> Path | None:
    configured = current_app.config.get("CRON_BACKUP_EXTERNAL_ROOT")
    if not configured:
        return None
    return Path(str(configured))


def _require_external() -> bool:
    return bool(current_app.config.get("CRON_BACKUP_REQUIRE_EXTERNAL", False))


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_manifest(path: Path, *, unit_key: str, db_file: Path) -> None:
    payload = {
        "job_key": "backup.daily",
        "unit_key": unit_key,
        "db_filename": db_file.name,
        "db_sha256": _sha256(db_file),
        "db_size_bytes": db_file.stat().st_size,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _copytree_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def run_backup_daily(*, unit_key: str) -> str:
    src = _sqlite_path()
    if not src.exists():
        raise RuntimeError(f"SQLite database not found: {src}")

    local_root = _local_backup_root()
    job_root = local_root / unit_key
    job_root.mkdir(parents=True, exist_ok=True)

    db_copy = job_root / f"vcdb-backup--{unit_key}.sqlite3"
    manifest = job_root / "MANIFEST.json"

    with sqlite3.connect(src) as source_conn:
        with sqlite3.connect(db_copy) as dest_conn:
            source_conn.backup(dest_conn)

    _write_manifest(manifest, unit_key=unit_key, db_file=db_copy)

    external_root = _external_backup_root()
    if external_root is None:
        if _require_external():
            raise RuntimeError("External backup root is required but missing.")
        return f"Local backup completed for {unit_key}."

    if not external_root.exists():
        if _require_external():
            raise RuntimeError(
                f"External backup root missing: {external_root}"
            )
        return f"Local backup completed for {unit_key}; external root missing."

    external_job_root = external_root / unit_key
    external_db_copy = external_job_root / db_copy.name
    external_manifest = external_job_root / manifest.name

    _copytree_file(db_copy, external_db_copy)
    _copytree_file(manifest, external_manifest)

    if _sha256(db_copy) != _sha256(external_db_copy):
        raise RuntimeError("External backup hash verification failed.")

    return f"Local and external backup completed for {unit_key}."
