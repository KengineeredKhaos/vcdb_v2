# app/lib/logging.py

import logging
from pathlib import Path

from .chrono import utc_now

"""
What to move into app/lib/logging.py

JSON formatter (your JSONLineFormatter).

Handler factory (file vs stdout).

Idempotent reset (remove duplicate handlers on repeated app inits).

Environment policy (dev → files; else → stdout).

3rd-party tuning (Werkzeug/Jinja levels).

Domain loggers wiring (vcdb.app, vcdb.audit, vcdb.jobs, vcdb.export).

Optional: a small adapter to inject common fields
(e.g., request_id) into all log records.

centralize all logging setup in app/__init__.py using inside "create_app"
    "configure_logging(app)"
then initstantiate the rest: db, blueprints, error handlers, etc.
"""


class JSONLineFormatter(logging.Formatter):
    """One JSON object per line, UTC timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        ts = utc_now.isoformat(timespec="seconds")
        base = {
            "ts": ts.replace("+00:00", "Z"),  # show explicit UTC
            "lvl": record.levelname,
            "logger": record.name,
        }
        # rest unchanged...
        if isinstance(record.msg, dict):
            base.update(record.msg)
        else:
            base["msg"] = record.getMessage()
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)


def _reset_logger(lg: logging.Logger) -> None:
    for h in list(lg.handlers):
        lg.removeHandler(h)


def configure_logging(app) -> None:
    """Single, idempotent logging setup. Call once per app instance."""
    is_dev = app.config.get("ENV") == "development" and not app.testing

    if is_dev:
        log_dir = Path(app.config.get("LOG_DIR", "app/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)

        def fh(filename: str) -> logging.Handler:
            h = logging.FileHandler(log_dir / filename, encoding="utf-8")
            h.setFormatter(JSONLineFormatter())
            h.setLevel(logging.INFO)
            return h

        # Flask app logger + framework loggers
        _reset_logger(app.logger)
        app.logger.setLevel(logging.INFO)
        app.logger.addHandler(fh("app.log"))

        for name in ("werkzeug", "jinja2"):
            lg = logging.getLogger(name)
            _reset_logger(lg)
            lg.addHandler(fh("app.log"))
            lg.setLevel(logging.INFO if name == "werkzeug" else logging.ERROR)

        # Domain loggers
        for name, file in (
            ("vcdb.app", "app.log"),
            ("vcdb.audit", "audit.log"),
            ("vcdb.jobs", "jobs.log"),
            ("vcdb.export", "export.log"),
        ):
            lg = logging.getLogger(name)
            _reset_logger(lg)
            lg.setLevel(logging.INFO)
            lg.addHandler(fh(file))
            lg.propagate = False
    else:
        root = logging.getLogger()
        _reset_logger(root)
        sh = logging.StreamHandler()
        sh.setFormatter(JSONLineFormatter())
        sh.setLevel(logging.INFO)
        root.addHandler(sh)
        root.setLevel(logging.INFO)
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("jinja2").setLevel(logging.ERROR)


def audit_logger() -> logging.Logger:
    """Convenience accessor for the audit channel."""
    return logging.getLogger("vcdb.audit")
