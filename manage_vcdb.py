#!/usr/bin/env python3
"""
manage_vcdb.py — one-entry launcher for VCDB v2

Lazy Dev Default:
    python manage_vcdb.py run

Dev on another port:
    python manage_vcdb.py run --env dev --host 0.0.0.0 --port 5100

Test with a twist:
    python manage_vcdb.py run --env test --port 5101 --no-debug


Production Mode will require some specific tuning:
    VCDB_DB="<SQLite path>"
    ATTACHMENTS_ROOT="/data/attachments" \
    VCDB_SECRET_KEY="supersecret" \

python manage_vcdb.py run --env prod --host 0.0.0.0 --port 8000 --no-debug


General Usage:
  python manage_vcdb.py run --env dev   [--host 0.0.0.0] [--port 5000] [--debug]
  python manage_vcdb.py run --env test  [--port 5001]
  python manage_vcdb.py run --env prod  [--host 0.0.0.0] [--port 8000]

Environment knobs (optional):
  VCDB_DB             -> SQLAlchemy URI override (especially for prod)
  VCDB_SECRET_KEY     -> Flask secret
  ATTACHMENTS_ROOT    -> root for blob storage (default var/data/attachments/<env>)
  VCDB_LOG_DIR        -> logs directory
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app import create_app


# ENV_TO_CONFIG = {
#     "dev": "config.DevConfig",
#     "test": "config.TestConfig",
#     "prod": "config.ProdConfig",  # ensure this class exists in config.py
# }


def _config_for(env: str) -> str:
    env = (env or "dev").lower()
    if env in ("dev", "development"):
        return "config.DevConfig"
    if env in ("test", "testing"):
        return "config.TestConfig"
    if env in ("prod", "production"):
        return "config.ProdConfig"
    raise SystemExit(f"Unknown --env {env}")


def ensure_dir(p: str | Path) -> str:
    path = Path(p)
    path.mkdir(parents=True, exist_ok=True)
    return str(path.resolve())


def pick_attachments_root(env: str) -> str:
    # Prefer explicit env var; otherwise default to an env-scoped folder.
    root = os.environ.get("ATTACHMENTS_ROOT")
    if not root or not root.strip():
        root = f"var/data/attachments/{env.lower()}"
        os.environ["ATTACHMENTS_ROOT"] = root
    return root


def print_banner(env: str, host: str, port: int, cfg: str, app):
    print("\n=== VCDB v2 — launcher ===")
    print(f"ENV                 : {env}")
    print(f"CONFIG OBJECT       : {cfg}")
    print(f"HOST:PORT           : {host}:{port}")
    print(
        f"DATABASE URI        : {app.config.get('SQLALCHEMY_DATABASE_URI')}"
    )
    print(f"ATTACHMENTS_ROOT    : {os.environ.get('ATTACHMENTS_ROOT')}")
    print(f"LOG DIR             : {app.config.get('LOG_DIR')}")
    print("==========================\n")


def run(env: str, host: str, port: int, debug_flag: bool):
    # Attachments root (env-scoped default) + ensure directory exists
    att_root = pick_attachments_root(env)
    abs_att = ensure_dir(att_root)

    # Optional: ensure a logs directory exists too
    ensure_dir(os.environ.get("VCDB_LOG_DIR", "app/logs"))

    cfg_object = _config_for(env)
    app = create_app(config_object=cfg_object)

    # Re-assert attachments path inside the app for clarity (services read env)
    os.environ["ATTACHMENTS_ROOT"] = abs_att

    # Debug preference:
    # - dev: default True unless --debug=False
    # - test/prod: default False unless explicitly set True (not recommended in prod)
    if debug_flag is None:
        debug = env == "dev"
    else:
        debug = bool(debug_flag)

    print_banner(env, host, port, cfg_object, app)
    app.run(host=host, port=port, debug=debug, use_reloader=debug)


def main():
    parser = argparse.ArgumentParser(description="VCDB v2 manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run the web server")
    run_p.add_argument(
        "--env", choices=["dev", "test", "prod"], default="dev"
    )
    run_p.add_argument("--host", default="127.0.0.1")
    run_p.add_argument("--port", type=int, default=5000)
    run_p.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        help="Force debug ON",
    )
    run_p.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="Force debug OFF",
    )
    run_p.set_defaults(debug=None)

    args = parser.parse_args()

    if args.cmd == "run":
        run(
            env=args.env,
            host=args.host,
            port=args.port,
            debug_flag=args.debug,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
