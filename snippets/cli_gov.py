# app/cli_gov.py
import json

import click
from flask.cli import with_appcontext

from app.extensions import current_actor_id, ulid
from app.slices.governance import services as gsvc


@click.group("gov")
def gov_group(): ...


@gov_group.command("seed")
@with_appcontext
def gov_seed():
    seeds = {
        "entity.allowed_roles": [
            "customer",
            "resource",
            "sponsor",
            "staff",
            "admin",
        ],
        "entity.resource_codes": [
            "vet",
            "clinic",
            "pharmacy",
            "groomer",
            "shelter",
            "transport",
            "housing",
            "counseling",
            "quartermaster",
            "events",
            "barber",
            "mobile_shower",
        ],
        "entity.us_states": [
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
            "DC",
            "PR",
        ],
    }
    actor = current_actor_id()
    reqid = ulid()
    for k, v in seeds.items():
        gsvc.policy_set(
            k, json.dumps(v), actor_id=actor, request_id=reqid, ptype="json"
        )
    click.echo("Governance policies seeded.")
