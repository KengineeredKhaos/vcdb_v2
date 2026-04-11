# config.py — clean, env-driven config
from __future__ import annotations

import os
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
    # ATTACHMENTS_ROOT = (env) var → default var/data/attachment


# ---------- Development ----------
class DevConfig(BaseConfig):
    ENV = "development"
    DEBUG = True
    SECRET_KEY = b"dev-not-secret"
    LOG_DIR = "app/logs"
    LOG_BACKUPS = 14
    LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB

    # Local sqlite file in repo /app/instance/dev.db
    DATABASE = str(BaseConfig.BASE_DIR / "app" / "instance" / "dev.db")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "VCDB_DB", f"sqlite:///{DATABASE}"
    )

    # Dev ergonomics
    AUTH_MODE = "stub"  # 'real' or 'stub' if iterating quickly on UI
    SESSION_COOKIE_NAME = "vcdb_dev_session"
    REMEMBER_COOKIE_NAME = "vcdb_dev_remember"
    ALLOW_HEADER_AUTH = True  # convenience; makes curl stubs easy
    AUTO_LOGIN_ADMIN = True
    DEV_ACTOR_ULID = "01KN8N389YT7YZE09QQB8N29P2"
    AUDIT_LOG_LEVEL = "DEBUG"

    # Boot Diagnostics (Dev-only)
    DEV_BOOT_DIAG = True
    DEV_BOOT_SANITY = True
    DEV_POLICY_FINGERPRINT = True
    DEV_POLICY_FINGERPRINT_LIST = True
    DEV_POLICY_HEALTH = True
    DEV_POLICY_HEALTH_LIST = True
    DEV_SCHEMA_CHECK = True
    DEV_SCHEMA_CHECK_DEEP = False
    # Functions for these tests are housed in app/dev/boot_diag.py


# ---------- Testing ----------
class TestConfig(BaseConfig):
    ENV = "testing"
    TESTING = True

    # Default to a repo-local, file-backed DB for easy inspection + determinism.
    # Overridable via VCDB_DB if you need a custom path/driver.
    TEST_DB = BaseConfig.BASE_DIR / "app" / "instance" / "test.db"
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "VCDB_DB", f"sqlite:///{TEST_DB}"
    )

    AUTH_MODE = "stub"
    AUTO_LOGIN_ADMIN = False  # test shouldn’t silently auto-admin
    WTF_CSRF_ENABLED = False
    LEDGER_CHECK_ON_BOOT = False
    ALLOW_HEADER_AUTH = True
    SESSION_COOKIE_NAME = "vcdb_test_session"
    REMEMBER_COOKIE_NAME = "vcdb_test_remember"


# ---------- Production ----------
class ProdConfig(BaseConfig):
    ENV = "production"
    DEBUG = False
    TESTING = False

    VCDB_DB = os.getenv("VCDB_DB", "").strip()
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{VCDB_DB}" if VCDB_DB else None

    AUTH_MODE = "real"
    ALLOW_HEADER_AUTH = False

    SESSION_COOKIE_NAME = "vcdb_prod_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"

    REMEMBER_COOKIE_NAME = "vcdb_prod_remember"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    AUDIT_LOG_LEVEL = os.environ.get("VCDB_AUDIT_LEVEL", "INFO")

    @classmethod
    def validate(cls):
        db_path = os.environ.get("VCDB_DB", "").strip()
        secret = os.environ.get("VCDB_SECRET_KEY", "").strip()

        if not db_path:
            raise RuntimeError(
                "ProdConfig requires VCDB_DB as an absolute DB file path."
            )
        if not secret or secret == "dev-not-secret":
            raise RuntimeError("ProdConfig requires a real VCDB_SECRET_KEY.")
        if cls.AUTH_MODE != "real":
            raise RuntimeError("ProdConfig AUTH_MODE must be 'real'.")
        if cls.ALLOW_HEADER_AUTH:
            raise RuntimeError("ProdConfig must not allow header auth.")


"""
Then set these when running prod:

export VCDB_DB="/srv/vcdb/var/db/prod.db"
export VCDB_SECRET_KEY="put-a-long-random-secret-here"
export ATTACHMENTS_ROOT="/srv/vcdb/var/uploads"
export VCDB_LOG_DIR="/srv/vcdb/var/log"

Notes:
- VCDB_DB is a filesystem path here, not a full SQLAlchemy URL.
- SESSION_COOKIE_SECURE=True assumes users reach the site over HTTPS.

SECRET_KEY Notes:

python -c 'import secrets; print(secrets.token_hex())'

Store the real key in the server environment or a root-readable env file
loaded by Apache

"""
