# app/lib/logging.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import gzip
import json
import logging
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.lib.chrono import now_iso8601_ms

# ----- JSON line formatter ----------------------------------------------------


class JSONLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": now_iso8601_ms(),
            "lvl": record.levelname,
            "logger": record.name,
        }
        # If message is already a dict-like JSON string, try to keep it
        try:
            msg_obj = json.loads(record.getMessage())
            if isinstance(msg_obj, dict):
                payload.update(msg_obj)
            else:
                payload["msg"] = record.getMessage()
        except Exception:
            payload["msg"] = record.getMessage()
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


# ----- helpers ----------------------------------------------------------------


def _reset_logger(lg: logging.Logger) -> None:
    for h in list(lg.handlers):
        lg.removeHandler(h)
    lg.setLevel(logging.NOTSET)
    lg.propagate = False


def _archiving_rotating_handler(
    base_dir: Path, filename: str, backups: int, max_bytes: int
) -> logging.Handler:
    """
    Live log at base_dir/filename.
    On rollover: move rotated file to base_dir/archive/<stem>-YYYYMMDD-HHMMSS.log.gz
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = base_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    live_path = base_dir / filename
    h = RotatingFileHandler(
        live_path,
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8",
        delay=False,
    )

    def namer(default_name: str) -> str:
        stem = Path(filename).stem  # "app"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{stem}-{ts}.log"  # basename; rotator will place it

    def rotator(source: str, dest: str) -> None:
        src = Path(source)
        final = archive_dir / Path(namer("ignored")).name
        shutil.move(str(src), str(final))
        gz_path = str(final) + ".gz"
        with open(final, "rb") as f_in, gzip.open(
            gz_path, "wb", compresslevel=6
        ) as f_out:
            shutil.copyfileobj(f_in, f_out)
        final.unlink(missing_ok=True)

    h.namer = namer
    h.rotator = rotator
    return h


# ----- main entry -------------------------------------------------------------


def configure_logging(flask_app) -> None:
    # Be robust even if someone accidentally passes the 'app' *module*.
    cfg = getattr(flask_app, "config", {}) or {}
    is_testing = bool(getattr(flask_app, "testing", cfg.get("TESTING", False)))
    is_dev = (not is_testing) and (
        bool(getattr(flask_app, "debug", False))
        or cfg.get("ENV") in {"dev", "development"}
        or bool(cfg.get("LOG_DIR"))
    )

    # Reset common loggers to avoid dupes / stale handlers
    for name in (
        "",
        "flask.app",
        "werkzeug",
        "jinja2",
        "app",
        "vcdb.app",
        "vcdb.audit",
        "vcdb.jobs",
        "vcdb.export",
    ):
        _reset_logger(logging.getLogger(name))

    log_dir = Path(cfg.get("LOG_DIR") or "app/logs")

    if is_dev:
        backups = int(cfg.get("LOG_BACKUPS", 14))
        max_bytes = int(cfg.get("LOG_MAX_BYTES", 10 * 1024 * 1024))

        main_h = _archiving_rotating_handler(
            log_dir, "app.log", backups, max_bytes
        )
        main_h.setFormatter(JSONLineFormatter())
        main_h.setLevel(logging.INFO)

        # 1) Attach to ROOT — guarantees we catch any logger name
        root = logging.getLogger()
        root.addHandler(main_h)
        root.setLevel(logging.INFO)
        root.propagate = False

        # 2) Also attach explicitly to the usual suspects (mirrors into app.log)
        for name in ("flask.app", "werkzeug", "jinja2", "app"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.INFO)
            lg.addHandler(main_h)
            lg.propagate = False

        # 3) Domain-specific files (optional)
        for name, file in (
            ("vcdb.app", "app.log"),
            ("vcdb.audit", "audit.log"),
            ("vcdb.jobs", "jobs.log"),
            ("vcdb.export", "export.log"),
        ):
            lg = logging.getLogger(name)
            lg.setLevel(logging.INFO)
            h = _archiving_rotating_handler(log_dir, file, backups, max_bytes)
            h.setFormatter(JSONLineFormatter())
            h.setLevel(logging.INFO)
            lg.addHandler(h)
            lg.propagate = False

    else:
        sh = logging.StreamHandler()
        sh.setFormatter(JSONLineFormatter())
        sh.setLevel(logging.INFO)
        root = logging.getLogger()
        root.addHandler(sh)
        root.setLevel(logging.INFO)
        root.propagate = False
