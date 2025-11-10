# app/cli_seed.py
from __future__ import annotations
import random
import click

from flask import current_app
from app.extensions import db
from app.lib.ids import new_ulid
from app.lib.chrono import now_iso8601_ms

# Seeds API (you uploaded this)
from app.seeds.core import (
    seed_rbac_from_policy,
    seed_domain_from_policy,
    seed_minimal_customer,
    seed_active_resource,
    seed_sponsor_with_policy,
)

# Models for POCs (entity “person” attached to an org)
from app.slices.entity.models import Entity, EntityPerson, EntityOrg

# If you have a formal “POC” link model later, swap this helper accordingly.
def _ensure_org_poc_pair(*, org_entity_ulid: str, label: str) -> list[str]:
    """Create two civilian POCs (Entity(kind='person')) for the given org.
    Returns the created POC entity ULIDs. Later you can add a formal link if/when that model exists.
    """
    ulids: list[str] = []
    ts = now_iso8601_ms()
    for i in range(2):
        e_ulid = new_ulid()
        person = EntityPerson(
            entity_ulid=e_ulid,
            first_name=f"{label} POC{i+1}",
            last_name="CIV",
            preferred_name=None,
        )
        ent = Entity(ulid=e_ulid, kind="person")
        # IsoTimestamps are columns; set explicitly to avoid NULL on NOT NULL columns during tests
        if hasattr(ent, "created_at_utc"): ent.created_at_utc = ts
        if hasattr(ent, "updated_at_utc"): ent.updated_at_utc = ts
        if hasattr(person, "created_at_utc"): person.created_at_utc = ts
        if hasattr(person, "updated_at_utc"): person.updated_at_utc = ts

        db.session.add_all([ent, person])
        ulids.append(e_ulid)

        # If/when you add an Org↔POC association table, insert that row here.

    db.session.flush()
    return ulids


@click.group("dev")
def dev_cmd() -> None:
    """Developer seeding utilities (idempotent where noted)."""
    pass


@dev_cmd.command("seed-role-codes")
def seed_role_codes() -> None:
    """Seed RBAC & Domain role codes from policy JSON (idempotent)."""
    n_rbac = seed_rbac_from_policy()
    n_domain = seed_domain_from_policy()
    click.echo(f"RBAC: +{n_rbac} (idempotent); Domain: +{n_domain} (idempotent)")


@dev_cmd.command("seed-foundation")
@click.option("--customers", type=int, default=5)
@click.option("--resources", type=int, default=3)
@click.option("--sponsors", type=int, default=3)
def seed_foundation(customers: int, resources: int, sponsors: int):
    # IMPORTANT: one transaction **per iteration** to avoid keeping a “closed”
    # session around when a single seed fails. Helpers do NOT commit/rollback.
    # Also, explicitly close/expire between iterations.

    # Resources
    for i in range(resources):
        label = f"Resource Org {i+1}"
        try:
            with db.session.begin():
                seed_active_resource(label=label)
        finally:
            # reset Session state for the next iteration
            db.session.expire_all()
            db.session.close()

    # Sponsors
    for i in range(sponsors):
        label = f"Sponsor Org {i+1}"
        try:
            with db.session.begin():
                seed_sponsor_with_policy(name=label)
        finally:
            db.session.expire_all()
            db.session.close()

    # Customers
    for i in range(customers):
        try:
            with db.session.begin():
                seed_minimal_customer(first="Test", last=f"User{i+1}")
        finally:
            db.session.expire_all()
            db.session.close()

    click.echo("OK — foundation seeded.")


# Optional: tiny “smoke” set for really fast local runs
# @dev_cmd.command("seed-smoke")
# def seed_smoke() -> None:
#     seed_rbac_from_policy()
#     seed_domain_from_policy()
#     r = seed_active_resource(label="Smoke Resource")
#     s = seed_sponsor_with_policy(name="Smoke Sponsor")
#     _ensure_org_poc_pair(org_entity_ulid=r.entity_ulid, label="Smoke Resource")
#     _ensure_org_poc_pair(org_entity_ulid=s.entity_ulid, label="Smoke Sponsor")
#     seed_minimal_customer(first="Smoke", last="User")
#     db.session.commit()
#     click.echo("Smoke seed OK")
