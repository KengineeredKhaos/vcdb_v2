# config.py — clean, env-driven config
from __future__ import annotations

import os
import tempfile
from pathlib import Path


# ---------- Common base ----------
class BaseConfig:
    # Security & Flask basics
    SECRET_KEY = os.environ.get("VCDB_SECRET_KEY", "dev-not-secret")

    # CSRF (tune per slice as needed)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # seconds

    # Paths / env
    BASE_DIR = Path(__file__).resolve().parent
    LOG_DIR = os.environ.get("VCDB_LOG_DIR", "app/logs")

    # SQLAlchemy (each subclass must set SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_DATABASE_URI: str | None = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # App-wide knobs
    VCDB_TIMEZONE = os.environ.get("VCDB_TIMEZONE", "America/Los_Angeles")
    VCDB_ARCHIVE = os.environ.get("VCDB_ARCHIVE", "./archive")

    # Audit logging
    AUDIT_LOG_PATH = os.environ.get("VCDB_AUDIT_LOG", "logs/audit.log")
    AUDIT_LOG_LEVEL = os.environ.get("VCDB_AUDIT_LEVEL", "INFO")  # INFO/DEBUG

    # Auth mode: 'real' | 'stub' (used by extensions/authn)
    AUTH_MODE = os.environ.get("VCDB_AUTH_MODE", "real")

    # Optional header auth (dev convenience)
    ALLOW_HEADER_AUTH = (
        os.environ.get("VCDB_ALLOW_HEADER_AUTH", "false").lower() == "true"
    )

    # Dev-only helper: which fields can log in
    LOGIN_FIELDS = ("email", "username")

    # Ledger checks (can be expensive at scale; leave True in dev)
    LEDGER_CHECK_ON_BOOT = (
        os.environ.get("VCDB_LEDGER_CHECK_ON_BOOT", "true").lower() == "true"
    )
    # Attachment Storage
    # ATTACHMENTS_ROOT = (env var) → default var/data/attachments


# ---------- Development ----------
class DevConfig(BaseConfig):
    ENV = "development"
    DEBUG = True

    # Local sqlite file in repo /var/app-instance/dev.db
    DATABASE = str(BaseConfig.BASE_DIR / "var" / "app-instance" / "dev.db")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "VCDB_DB", f"sqlite:///{DATABASE}"
    )

    # Dev ergonomics
    AUTH_MODE = "stub"  # 'real' or 'stub' if iterating quickly on UI
    ALLOW_HEADER_AUTH = (
        os.environ.get("VCDB_ALLOW_HEADER_AUTH", "false").lower() == "true"
    )
    AUTO_LOGIN_ADMIN = True
    AUDIT_LOG_LEVEL = "DEBUG"


# ---------- Testing ----------
class TestConfig(BaseConfig):
    ENV = "testing"
    TESTING = True

    _fd, _path = tempfile.mkstemp(prefix="vcdb-test-", suffix=".db")
    os.close(_fd)
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_path}"
    # <-- use the file-backed DB
    AUTH_MODE = "stub"
    WTF_CSRF_ENABLED = False
    LEDGER_CHECK_ON_BOOT = False
    ALLOW_HEADER_AUTH = True


# ---------- Production ----------
class ProdConfig(BaseConfig):
    DEBUG = False
    TESTING = False

    # Lazy/default DB path — do NOT raise at import-time
    VCDB_DB = os.getenv("VCDB_DB")
    SQLALCHEMY_DATABASE_URI = (
        f"sqlite:///{VCDB_DB}"
        if VCDB_DB
        else "sqlite:///var/app-instance/prod.db"
    )

    AUTH_MODE = "real"
    ALLOW_HEADER_AUTH = False
    AUDIT_LOG_LEVEL = os.environ.get("VCDB_AUDIT_LEVEL", "INFO")

    @classmethod
    def validate(cls):
        """
        Call this only when actually using ProdConfig to ensure env is set.
        """
        if not cls.VCDB_DB:
            raise RuntimeError(
                "ProdConfig requires VCDB_DB (absolute path to the SQLite DB). "
                "Either set VCDB_DB or override SQLALCHEMY_DATABASE_URI."
            )


"""
Then set these when running prod:

export VCDB_DB="sqlite:////data/vcdb.db"   # or a Postgres URL
export VCDB_SECRET_KEY="change-me"
export ATTACHMENTS_ROOT="/data/vcdb-attachments"


"""
