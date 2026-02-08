#!/usr/bin/env python3
"""
DB admin helper for VCDB v2.

Usage examples:
  # Non-destructive: create only the missing tables for the selected env
  python scripts/db_create_all.py --env dev --mode create

  # Dry check: prints model tables vs existing DB tables
  python scripts/db_create_all.py --env dev --mode check

  # Destructive: drop ALL tables then create fresh
  python scripts/db_create_all.py --env test --mode recreate --yes-i-am-sure

  # Destructive: drop all tables only
  python scripts/db_create_all.py --env dev --mode drop --yes-i-am-sure
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import inspect

# Boot the app so SQLAlchemy is initialized
from app import create_app
from app.extensions import db

ENV_TO_CONFIG = {
    "dev": "config.DevConfig",
    "test": "config.TestConfig",
    "prod": "config.ProdConfig",
}


def _discover_slice_model_modules(root: str = "app/slices") -> list[str]:
    """
    Find app.slices.<slice>.models modules to import so their tables are
    registered on SQLAlchemy metadata before create_all() / drop_all().
    """
    modules: list[str] = []
    base = Path(root)
    if not base.exists():
        return modules
    for child in base.iterdir():
        if child.is_dir() and (child / "models.py").exists():
            mod = f"app.slices.{child.name}.models"
            modules.append(mod)
    return modules


def _import_modules(modules: Iterable[str]) -> None:
    for m in modules:
        try:
            importlib.import_module(m)
        except Exception as e:
            print(f"[WARN] Could not import {m}: {e}")


def _print_summary(app, mode: str):
    print("\n=== VCDB v2 — DB admin ===")
    print(f"ENV                 : {app.config.get('ENV') or 'unknown'}")
    print(f"CONFIG OBJECT       : {app.config.get('CONFIG_NAME') or 'n/a'}")
    print(
        f"SQLALCHEMY URI      : {app.config.get('SQLALCHEMY_DATABASE_URI')}"
    )
    print(f"MODE                : {mode}")
    print("==========================\n")


def _check(app):
    with app.app_context():
        insp = inspect(db.engine)
        db_tables = set(insp.get_table_names())
        model_tables = set(db.metadata.tables.keys())

        missing = model_tables - db_tables
        extra = (
            db_tables - model_tables
        )  # tables in DB not declared by current models

        print("Model-declared tables:")
        for t in sorted(model_tables):
            print(f"  - {t}")
        print("\nExisting DB tables:")
        for t in sorted(db_tables):
            print(f"  - {t}")

        print("\n--- Diff ---")
        print(
            f"Missing in DB (will be created by 'create'): {sorted(missing) or 'None'}"
        )
        print(f"Extra in DB (unknown to models): {sorted(extra) or 'None'}")
        print("------------")


def run(mode: str, env: str, sure: bool):
    if env not in ENV_TO_CONFIG:
        raise SystemExit("Invalid --env. Choose dev|test|prod.")

    # Prepare app
    cfg_obj = ENV_TO_CONFIG[env]
    app = create_app(config_object=cfg_obj)
    # store for summary
    app.config["CONFIG_NAME"] = cfg_obj

    # Ensure all slice models are registered
    # (Add core slices that might not be under app/slices if needed)
    base_modules = [
        "app.slices.entity.models",
        "app.slices.auth.models",
        "app.slices.customers.models",
        "app.slices.resources.models",
        "app.slices.attachments.models",
    ]
    _import_modules(base_modules)
    _import_modules(_discover_slice_model_modules())

    _print_summary(app, mode)

    with app.app_context():
        if mode == "check":
            _check(app)
            return

        if mode == "create":
            # Creates only tables that do not exist; does NOT alter existing tables or add indexes on them.
            db.create_all()
            print("create_all() complete. (Non-destructive)")
            return

        if mode == "drop":
            if not sure:
                raise SystemExit("Refusing to drop without --yes-i-am-sure")
            db.drop_all()
            print("drop_all() complete. (Destructive)")
            return

        if mode == "recreate":
            if not sure:
                raise SystemExit(
                    "Refusing to recreate without --yes-i-am-sure"
                )
            db.drop_all()
            db.create_all()
            print("drop_all() + create_all() complete. (Destructive)")
            return

        raise SystemExit("Unknown --mode. Use create|drop|recreate|check.")


def main():
    p = argparse.ArgumentParser(description="VCDB v2 DB admin")
    p.add_argument("--env", choices=["dev", "test", "prod"], default="dev")
    p.add_argument(
        "--mode",
        choices=["create", "drop", "recreate", "check"],
        default="create",
    )
    p.add_argument(
        "--yes-i-am-sure",
        action="store_true",
        help="Required for destructive modes",
    )
    args = p.parse_args()
    run(mode=args.mode, env=args.env, sure=args.yes_i_am_sure)


if __name__ == "__main__":
    main()
