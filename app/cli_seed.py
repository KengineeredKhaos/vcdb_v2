# app/cli_dev.py (or cli_seed.py)
import click
from flask.cli import with_appcontext
from app.seeds.core import seed_active_resource, seed_sponsor_with_policy, seed_minimal_customer

@click.group("seed")
def seed_grp(): ...

@seed_grp.command("customer")
@with_appcontext
def seed_customer():
    out = seed_minimal_customer()
    click.echo(vars(out))

@seed_grp.command("resource")
@click.option("--code", default="res-dev-001")
@with_appcontext
def seed_resource(code):
    out = seed_active_resource(code=code)
    click.echo(vars(out))

@seed_grp.command("sponsor")
@click.option("--code", default="spon-dev-001")
@with_appcontext
def seed_sponsor(code):
    out = seed_sponsor_with_policy(code=code)
    click.echo(vars(out))
