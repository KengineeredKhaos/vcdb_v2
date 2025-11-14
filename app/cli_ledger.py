# app/cli_ledger.py
import click
from app.cli import echo_db_banner
from app.slices.ledger.services import verify_chain

@click.group("ledger")
def ledger_group():
    """Ledger tools (verify chains; repair lives in devtools)."""

@ledger_group.command("verify")
@click.option("--chain", "chain_key", default=None, help="Limit to a single chain")
def verify(chain_key):
    echo_db_banner("ledger-verify")
    res = verify_chain(chain_key)
    if not res.get("ok"):
        raise click.ClickException(f"Ledger verify failed: {res}")
    click.secho(f"OK — verified {res.get('checked', 0)} events across {len(res.get('chains', {}))} chains", fg="green")
