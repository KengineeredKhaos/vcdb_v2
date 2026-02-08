# app/cli_seed.py

"""
app.cli_seed

Developer-only database seeding commands for VCDB v2.

Primary workflow:
    flask seed bootstrap --fresh --force

Bootstrap behavior:
- Optional: delete the SQLite database file (--fresh requires --force).
- Run Alembic migrations to head (flask_migrate.upgrade()).
- Seed policy-derived vocabulary/code tables (RBAC roles + domain roles).
- Seed baseline domain data:
    * Resources (each anchored to an Entity(org))
    * Sponsors  (each anchored to an Entity(org))
    * Two POC people per org (Entity(person), role='civilian')
    * Link POCs via slice-owned POC link tables using slice services
    * Customers (Entity(person) + Customer + CustomerEligibility)

Operational guarantees:
- Single transaction boundary: all writes are staged and committed once at the end.
- On any exception, the session is rolled back and the command fails cleanly.
"""

from __future__ import annotations

from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy.engine.url import make_url

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.seeds import core as seed_core

seed_cmd = click.Group("seed")


def _sqlite_db_path() -> Path:
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    url = make_url(uri)
    if url.drivername != "sqlite":
        raise click.ClickException(
            "bootstrap --fresh only supports sqlite URIs"
        )
    if not url.database or url.database == ":memory:":
        raise click.ClickException(
            "sqlite database path missing/invalid in SQLALCHEMY_DATABASE_URI"
        )
    return Path(url.database)


def _fresh_sqlite_db(*, force: bool) -> None:
    path = _sqlite_db_path()

    if path.exists() and not force:
        raise click.ClickException(
            f"Refusing to delete existing DB without --force: {path}"
        )

    # Close out any handles before deleting
    db.session.remove()
    db.engine.dispose()

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()


def seed_bootstrap_impl(
    *,
    fresh: bool,
    force: bool,
    faker_seed: int,
    customers: int,
    resources: int,
    sponsors: int,
) -> None:
    """
    Plain Python seeding implementation.
    Safe for pytest to call inside an app context.

    NOTE: In tests you normally want fresh=False/force=False because pytest uses
    its own sqlite test DB (created in tests/conftest.py).
    """
    if fresh:
        _fresh_sqlite_db(force=force)

    # Always migrate to latest
    alembic_upgrade()

    faker = seed_core.make_faker(faker_seed)

    # Role codes (no commit yet)
    n_rbac, n_domain = seed_core.seed_policy_codes_no_commit(db.session)

    # Late imports so app boots even if slices change during refactors
    from app.slices.resources.services import resource_link_poc
    from app.slices.sponsors.services import sponsor_link_poc

    # Resources + POCs
    for i in range(resources):
        label = f"Resource Org {i + 1}"
        res = seed_core.seed_active_resource(
            sess=db.session, label=label, faker=faker
        )

        pocs = seed_core.seed_org_poc_pair(
            db.session,
            org_entity_ulid=res.entity_ulid,
            label=label,
            faker=faker,
        )

        ts = now_iso8601_ms()
        for j, person_entity_ulid in enumerate(pocs):
            resource_link_poc(
                resource_entity_ulid=res.resource_entity_ulid,
                person_entity_ulid=person_entity_ulid,
                scope=None,
                rank=j,
                is_primary=(j == 0),
                window={"from": ts, "to": None},
                org_role="primary" if j == 0 else "backup",
                actor_ulid="seed",
                request_id=new_ulid(),
            )

    # Sponsors + POCs
    for i in range(sponsors):
        label = f"Sponsor Org {i + 1}"
        sres = seed_core.seed_sponsor_with_policy(
            sess=db.session, label=label, faker=faker
        )

        pocs = seed_core.seed_org_poc_pair(
            db.session,
            org_entity_ulid=sres.entity_ulid,
            label=label,
            faker=faker,
        )

        ts = now_iso8601_ms()
        for j, person_entity_ulid in enumerate(pocs):
            sponsor_link_poc(
                sponsor_entity_ulid=sres.sponsor_entity_ulid,
                person_entity_ulid=person_entity_ulid,
                scope=None,
                rank=j,
                is_primary=(j == 0),
                window={"from": ts, "to": None},
                org_role="primary" if j == 0 else "backup",
                actor_ulid="seed",
                request_id=new_ulid(),
            )

    # Customers
    for i in range(customers):
        seed_core.seed_minimal_customer(
            sess=db.session,
            first="Test",
            last=f"User{i + 1}",
            faker=faker,
        )

    db.session.commit()

    click.echo(
        f"OK — bootstrap complete. (RBAC +{n_rbac}, Domain +{n_domain}, "
        f"resources={resources}, sponsors={sponsors}, customers={customers})"
    )
    return True


@seed_cmd.command("bootstrap")
@with_appcontext
@click.option(
    "--fresh",
    is_flag=True,
    help="Delete sqlite dev.db before migrating+seeding.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Required with --fresh to actually delete the DB file.",
)
@click.option("--faker-seed", type=int, default=1337, show_default=True)
@click.option("--customers", type=int, default=5, show_default=True)
@click.option("--resources", type=int, default=3, show_default=True)
@click.option("--sponsors", type=int, default=3, show_default=True)
def seed_bootstrap(
    fresh: bool,
    force: bool,
    faker_seed: int,
    customers: int,
    resources: int,
    sponsors: int,
):
    try:
        click.echo("seed-bootstrap")
        seed_bootstrap_impl(
            fresh=fresh,
            force=force,
            faker_seed=faker_seed,
            customers=customers,
            resources=resources,
            sponsors=sponsors,
        )
    except Exception as e:
        db.session.rollback()
        raise click.ClickException(
            f"bootstrap failed; rolled back: {e}"
        ) from e
