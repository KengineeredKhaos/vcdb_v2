#!/usr/bin/env python3
"""
VCDB v2 launcher / CLI entrypoint

Usage:
  # Run the dev server
  python manage_vcdb.py run --env dev

  # Flask CLI (custom commands like ledger-verify)
  flask --app manage_vcdb.py ledger-verify
  flask --app manage_vcdb.py ledger-verify --chain entity
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

# -----------------
# Config mapping
# -----------------


def _config_for(env: str):
    """Return a config object class for the given env."""
    from config import (
        DevConfig,
        ProdConfig,
        TestConfig,
    )  # local import avoids early side-effects

    env = (env or "dev").lower()
    if env in ("prod", "production"):
        return ProdConfig
    if env in ("test", "testing"):
        return TestConfig
    return DevConfig  # default


# -----------------
# Small helpers
# -----------------


def ensure_dir(path: str) -> str:
    """Ensure a directory exists and return its absolute path."""
    abspath = os.path.abspath(path)
    os.makedirs(abspath, exist_ok=True)
    return abspath


def pick_attachments_root(env: str) -> str:
    """Choose an attachments root based on env (overridable by env var)."""
    root = os.environ.get("ATTACHMENTS_ROOT")
    if root:
        return root
    base = os.path.join("var", "data", "attachments", env)
    return base


def print_banner(
    env: str, host: str, port: int, cfg_obj: Any, flask_app: Any
) -> None:
    """Pretty banner showing key runtime info. Call once in the main process."""
    db_uri = flask_app.config.get("SQLALCHEMY_DATABASE_URI", "<unset>")
    att_root = os.environ.get("ATTACHMENTS_ROOT", "<unset>")
    log_dir = os.environ.get("VCDB_LOG_DIR", "app/logs")
    print("\n=== VCDB v2 — launcher ===")
    print(f"ENV                 : {env}")
    print(f"CONFIG OBJECT       : {cfg_obj.__module__}.{cfg_obj.__name__}")
    print(f"HOST:PORT           : {host}:{port}")
    print(f"DATABASE URI        : {db_uri}")
    print(f"ATTACHMENTS_ROOT    : {att_root}")
    print(f"LOG DIR             : {log_dir}")
    print("==========================\n")


# -----------------
# Flask app factory wrapper for Flask CLI
# (--app manage_vcdb.py)
# -----------------


def create_app():
    # Prefer VCDB_ENV, then FLASK_ENV, default 'dev'
    env = os.environ.get("VCDB_ENV") or os.environ.get("FLASK_ENV") or "dev"
    debug = env == "dev"

    # Ensure dirs that the app expects
    att_root = pick_attachments_root(env)
    abs_att = ensure_dir(att_root)
    os.environ["ATTACHMENTS_ROOT"] = abs_att
    ensure_dir(os.environ.get("VCDB_LOG_DIR", "app/logs"))

    # When running in testing via CLI/Flask CLI,
    # default DB to app/instance/test.db
    if (
        env in ("test", "testing")
        and "SQLALCHEMY_DATABASE_URI" not in os.environ
    ):
        inst_dir = ensure_dir(os.path.join("app", "instance"))
        test_db_path = os.path.abspath(os.path.join(inst_dir, "test.db"))
        os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{test_db_path}"
    os.environ["VCDB_ENV"] = env

    # Build the Flask app with the selected config
    cfg_object = _config_for(env)
    from app import (
        create_app as _create_flask_app,
    )  # import here to avoid cycles

    flask_app = _create_flask_app(config_object=cfg_object)

    # CLI commands already registered by the factory

    # Optional: print a short banner once when using CLI (suppressed by default)
    is_main = os.environ.get("WERKZEUG_RUN_MAIN") in (None, "true")
    if is_main or not debug:
        print_banner(env, "CLI", 0, cfg_object, flask_app)

    return flask_app


# -----------------
# Run server
# (python manage_vcdb.py run ...)
# -----------------


def run(env: str, host: str, port: int | None, debug_flag: bool | None):
    # Decide debug FIRST
    debug = (env == "dev") if debug_flag is None else bool(debug_flag)

    # Choose a sensible default port per environment, overrideable by VCDB_PORT/--port
    default_port = 5001 if env in ("test", "testing") else 5000
    port = int(os.environ.get("VCDB_PORT", port or default_port))

    # Ensure expected directories / env
    att_root = pick_attachments_root(env)
    abs_att = ensure_dir(att_root)
    os.environ["ATTACHMENTS_ROOT"] = abs_att
    ensure_dir(os.environ.get("VCDB_LOG_DIR", "app/logs"))

    # When running the testing server, default DB to app/instance/test.db
    if (
        env in ("test", "testing")
        and "SQLALCHEMY_DATABASE_URI" not in os.environ
    ):
        inst_dir = ensure_dir(os.path.join("app", "instance"))
        test_db_path = os.path.abspath(os.path.join(inst_dir, "test.db"))
        os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{test_db_path}"
    os.environ["VCDB_ENV"] = env

    # Build app
    cfg_object = _config_for(env)
    from app import (
        create_app as _create_flask_app,
    )  # import here to avoid cycles

    app = _create_flask_app(config_object=cfg_object)

    # Register custom CLI commands on this app instance
    from app.cli import register_cli

    register_cli(app)

    # Print banner only in the main process (avoid duplicate prints under reloader)
    is_main = os.environ.get("WERKZEUG_RUN_MAIN") in (None, "true")
    if is_main or not debug:
        print_banner(env, host, port, cfg_object, app)

    # Single run call
    app.run(host=host, port=port, debug=debug, use_reloader=debug)


# -----------------
# Argparse entrypoint
# -----------------


def main(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="manage_vcdb.py", description="VCDB v2 app manager"
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
        "--debug", action="store_true", help="Force debug=True"
    )
    p_run.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="Force debug=False",
    )
    p_run.set_defaults(debug=None)  # None => infer from env

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
