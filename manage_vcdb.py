#!/usr/bin/env python3
"""
VCDB v2 launcher / CLI entrypoint

This file is:
- the Flask CLI wrapper
- the local dev/test server launcher

This file is NOT:
- the Apache production entrypoint
- the real Flask app factory

The real app factory lives in app/__init__.py.
Apache/mod_wsgi should eventually use a separate wsgi.py.

Before running any migration/upgrade operations, ensure which db you're on:

    flask --app manage_vcdb.py shell

Then, at the python prompt ( >>> ) paste:

    from flask import current_app
    print(current_app.config.get("SQLALCHEMY_DATABASE_URI"))

In the case where dev.db needs to be upgraded to the latest migration:

    flask --app manage_vcdb.py db migrate
    flask --app manage_vcdb.py db upgrade
    export VCDB_ENV=testing
    unset VCDB_DB
    flask --app manage_vcdb.py db upgrade


If test.db grows too large to parse effectively or turns into a bag of snakes:

export VCDB_ENV=testing
unset VCDB_DB
rm -f app/instance/test.db
flask --app manage_vcdb.py db upgrade

Be sure you get back on the dev environment

"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# -----------------
# Config mapping
# -----------------


def _config_for(env: str):
    """Return the config class for the requested environment."""
    from config import DevConfig, ProdConfig, TestConfig

    env = (env or "dev").strip().lower()

    if env in ("prod", "production"):
        return ProdConfig
    if env in ("test", "testing"):
        return TestConfig
    return DevConfig


def _normalize_env_name(env: str) -> str:
    """Return one canonical env string."""
    env = (env or "dev").strip().lower()

    if env in ("prod", "production"):
        return "production"
    if env in ("test", "testing"):
        return "testing"
    return "development"


# -----------------
# Small helpers
# -----------------


def ensure_dir(path: str) -> str:
    """
    Ensure a directory exists and return its absolute path.

    Convenience helper for dev/test paths.
    Production should pass validation first, then we may create the
    directory if it is expected to exist as part of deployment layout.
    """
    abspath = os.path.abspath(path)
    os.makedirs(abspath, exist_ok=True)
    return abspath


def _default_test_db_path() -> str:
    """Return the default repo-local test DB path."""
    inst_dir = ensure_dir(os.path.join("app", "instance"))
    return os.path.abspath(os.path.join(inst_dir, "test.db"))


def _default_dev_attachments_root() -> str:
    """Default writable attachments path for local development."""
    return os.path.abspath(os.path.join("app", "instance", "uploads"))


def _default_test_attachments_root() -> str:
    """Default writable attachments path for local testing."""
    return os.path.abspath(os.path.join("app", "instance", "test-uploads"))


def _default_dev_log_dir() -> str:
    """Default local log dir."""
    return os.path.abspath(os.path.join("app", "logs"))


def _validate_prod_runtime_env() -> None:
    """
    Fail loudly if required production runtime env vars are missing.

    These are runtime path concerns, distinct from ProdConfig.validate(),
    which should validate config/auth/secret expectations.
    """
    missing: list[str] = []

    for key in ("VCDB_DB", "ATTACHMENTS_ROOT", "VCDB_LOG_DIR"):
        if not os.environ.get(key, "").strip():
            missing.append(key)

    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Production startup requires explicit runtime paths for: "
            f"{joined}"
        )


def prepare_runtime_env(env: str) -> tuple[str, Any]:
    """
    Normalize env name, fill in local defaults where appropriate, validate
    production expectations, and return:

        (canonical_env_name, config_class)
    """
    env_name = _normalize_env_name(env)
    cfg_object = _config_for(env)

    os.environ["VCDB_ENV"] = env_name

    # Local defaults only for development/testing.
    if env_name == "testing":
        if not os.environ.get("VCDB_DB", "").strip():
            os.environ["VCDB_DB"] = _default_test_db_path()

        if not os.environ.get("ATTACHMENTS_ROOT", "").strip():
            os.environ["ATTACHMENTS_ROOT"] = _default_test_attachments_root()

        if not os.environ.get("VCDB_LOG_DIR", "").strip():
            os.environ["VCDB_LOG_DIR"] = _default_dev_log_dir()

    elif env_name == "development":
        if not os.environ.get("ATTACHMENTS_ROOT", "").strip():
            os.environ["ATTACHMENTS_ROOT"] = _default_dev_attachments_root()

        if not os.environ.get("VCDB_LOG_DIR", "").strip():
            os.environ["VCDB_LOG_DIR"] = _default_dev_log_dir()

    elif env_name == "production":
        _validate_prod_runtime_env()
        cfg_object.validate()

    # Make the dirs exist after validation/defaulting.
    ensure_dir(os.environ["ATTACHMENTS_ROOT"])
    ensure_dir(os.environ["VCDB_LOG_DIR"])

    return env_name, cfg_object


def print_banner(
    env: str,
    host: str,
    port: int,
    cfg_obj: Any,
    flask_app: Any,
) -> None:
    """Pretty banner showing key runtime info."""
    db_uri = flask_app.config.get("SQLALCHEMY_DATABASE_URI", "<unset>")
    att_root = os.environ.get("ATTACHMENTS_ROOT", "<unset>")
    log_dir = os.environ.get("VCDB_LOG_DIR", "<unset>")

    print("\n=== VCDB v2 — launcher ===")
    print(f"ENV                 : {env}")
    print(f"CONFIG OBJECT       : {cfg_obj.__module__}.{cfg_obj.__name__}")
    print(f"HOST:PORT           : {host}:{port}")
    print(f"DATABASE URI        : {db_uri}")
    print(f"ATTACHMENTS_ROOT    : {att_root}")
    print(f"LOG DIR             : {log_dir}")
    print("==========================\n")


# -----------------
# Flask CLI app factory
# (--app manage_vcdb.py)
# -----------------


def create_app():
    """
    Flask CLI wrapper factory.

    Flask CLI imports this file and calls create_app() so commands like:
        flask --app manage_vcdb.py seed bootstrap
    can build the real Flask app.
    """
    requested = (
        os.environ.get("VCDB_ENV") or os.environ.get("FLASK_ENV") or "dev"
    )
    env_name, cfg_object = prepare_runtime_env(requested)

    from app import create_app as _create_flask_app

    flask_app = _create_flask_app(config_object=cfg_object)

    # Optional CLI banner; off by default to reduce duplicate startup noise.
    if os.environ.get("VCDB_CLI_BANNER", "").strip().lower() == "true":
        is_main = os.environ.get("WERKZEUG_RUN_MAIN") in (None, "true")
        if is_main:
            print_banner(env_name, "CLI", 0, cfg_object, flask_app)

    return flask_app


# -----------------
# Run local dev/test server
# -----------------


def run(env: str, host: str, port: int | None, debug_flag: bool | None):
    """
    Run the built-in Flask server.

    This is for local development/testing only.
    Apache/mod_wsgi should use a separate wsgi.py.
    """
    env_name, cfg_object = prepare_runtime_env(env)

    default_port = 5001 if env_name == "testing" else 5000
    port = int(os.environ.get("VCDB_PORT", port or default_port))

    debug = (
        env_name == "development" if debug_flag is None else bool(debug_flag)
    )

    if env_name == "production" and debug:
        raise RuntimeError("Refusing to run production with debug enabled.")

    from app import create_app as _create_flask_app

    flask_app = _create_flask_app(config_object=cfg_object)

    is_main = os.environ.get("WERKZEUG_RUN_MAIN") in (None, "true")
    if is_main or not debug:
        print_banner(env_name, host, port, cfg_object, flask_app)

    flask_app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug,
    )


# -----------------
# Argparse entrypoint
# -----------------


def main(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        prog="manage_vcdb.py",
        description="VCDB v2 app manager",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run the Flask development server")
    p_run.add_argument(
        "--env",
        default="dev",
        choices=["dev", "test", "prod", "production", "testing"],
        help="Environment",
    )
    p_run.add_argument("--host", default="127.0.0.1", help="Host")
    p_run.add_argument("--port", default=5000, type=int, help="Port")
    p_run.add_argument(
        "--debug",
        action="store_true",
        help="Force debug=True",
    )
    p_run.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="Force debug=False",
    )
    p_run.set_defaults(debug=None)

    args = parser.parse_args(argv)

    if args.command == "run":
        run(
            env=args.env,
            host=args.host,
            port=args.port,
            debug_flag=args.debug,
        )
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
