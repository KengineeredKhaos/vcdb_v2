# app/cli.py
import click
from app.extensions.contracts.ledger import v2 as L
from app.lib.ids import new_ulid


def register_cli(app):
    @app.cli.command("emit-smoke")
    @click.option("--n", default=1, show_default=True, help="How many events")
    @click.option("--chain", default="smoke", show_default=True)
    def emit_smoke(n, chain):
        for i in range(n):
            r = L.emit(
                domain=chain,
                operation=f"ping{i}",
                request_id=new_ulid(),
                actor_ulid=None,
                target_ulid=None,
            )
            click.echo(r)
