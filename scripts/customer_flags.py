# scripts/customer_flags.py (optional CLI helper for dev)
#!/usr/bin/env python3
from __future__ import annotations
import click
from app import create_app, db
from app.slices.customers.services.eligibility import (
    set_verification_flags,
    set_tier_min,
)


@click.group()
def cli():
    pass


@cli.command("set-flags")
@click.argument("customer_ulid")
@click.option("--vet/--no-vet", default=None, help="Veteran verified flag")
@click.option(
    "--homeless/--no-homeless", default=None, help="Homeless verified flag"
)
def set_flags(customer_ulid, vet, homeless):
    snap = set_verification_flags(
        customer_ulid, veteran=vet, homeless=homeless
    )
    click.echo(snap)


@cli.command("set-tier")
@click.argument("customer_ulid")
@click.option("--tier1", type=int)
@click.option("--tier2", type=int)
@click.option("--tier3", type=int)
def set_tier(customer_ulid, tier1, tier2, tier3):
    snap = set_tier_min(customer_ulid, tier1=tier1, tier2=tier2, tier3=tier3)
    click.echo(snap)


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        cli()
