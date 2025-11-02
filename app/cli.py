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


def register_cli(app) -> None:
    # Import here so importing app.__init__ doesn’t eagerly pull every CLI module
    from app.cli_gov import governance_group
    from app.cli_finance import finance_group
    from app.cli_dev import dev_group  # ← new

    app.cli.add_command(governance_group)
    app.cli.add_command(finance_group)
    app.cli.add_command(dev_group)
