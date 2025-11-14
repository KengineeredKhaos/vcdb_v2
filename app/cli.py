"""
CLI Primer (read me first)

We organize commands by domain:
- governance → app/cli_gov.py
- finance    → app/cli_finance.py
- dev        → app/cli_dev.py  (ops/dev utilities; never required in production)

This file just registers those command groups on the Flask app’s CLI.
Add new groups in their own module and import/register them here.
"""

from __future__ import annotations
import click
from flask import current_app

def register_cli(app) -> None:
    # Import here so importing app.__init__ doesn’t eagerly pull every CLI module
    from app.cli_gov import governance_group
    from app.cli_finance import finance_group
    from app.cli_dev import dev_group  # ← new
    from app.cli_ledger import ledger_group
    from app.cli_seed import seed_cmd

    app.cli.add_command(governance_group)
    app.cli.add_command(finance_group)
    app.cli.add_command(dev_group)
    app.cli.add_command(seed_cmd)
    app.cli.add_command(ledger_group)


def echo_db_banner(tag: str = ""):
    cfg = current_app.config
    tag = f" {tag}" if tag else ""
    click.secho(
        f"[vcdb{tag}] ENV={cfg.get('APP_MODE','?')} "
        f"DB={cfg.get('SQLALCHEMY_DATABASE_URI','?')}",
        fg="cyan",
    )
