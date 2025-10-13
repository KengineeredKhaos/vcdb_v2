#!/usr/bin/env python3
# vcdb-v2/scripts/seed_dev.py
from __future__ import annotations
import sys
import json

from app import create_app
from app.extensions import db
from sqlalchemy import inspect

from app.lib.chrono import utc_now
from app.lib.ids import new_ulid


def _has_table(name: str) -> bool:
    try:
        insp = inspect(db.engine)
        return name in set(insp.get_table_names())
    except Exception:
        return False


def seed_policies():
    try:
        from app.slices.governance import services as gov

        # Bootstrap all registered policies (inserts defaults if missing)
        for family in gov.list_policy_keys():
            gov.get_policy_value(family)
        print("✓ governance policies bootstrapped")
    except Exception as e:
        print(f"• governance skipped: {e}")


def seed_entities():
    try:
        from app.slices.entity import services as ent

        # Person: Jane Doe (becomes a Customer)
        jane_ulid = ent.ensure_person(
            first_name="Jane",
            last_name="Doe",
            email="jane@example.org",
            phone="+1-555-0100",
            request_id=new_ulid(),
            actor_id=None,
        )
        ent.upsert_address(
            entity_id=jane_ulid,
            purpose="physical",
            address1="123 Main St",
            address2=None,
            city="Reno",
            state="NV",
            postal="89501",
            tz="America/Los_Angeles",
            request_id=new_ulid(),
            actor_id=None,
        )
        ent.ensure_role(
            entity_id=jane_ulid,
            role_code="customer",
            request_id=new_ulid(),
            actor_id=None,
        )

        # Org A: Helping Hands (Resource)
        hh_ulid = ent.ensure_org(
            legal_name="Helping Hands Community Org",
            doing_business_as=None,
            ein="12-3456789",
            request_id=new_ulid(),
            actor_id=None,
        )
        ent.upsert_address(
            entity_id=hh_ulid,
            purpose="physical",
            address1="200 Service Ave",
            address2="Suite 10",
            city="Reno",
            state="NV",
            postal="89502",
            tz="America/Los_Angeles",
            request_id=new_ulid(),
            actor_id=None,
        )
        ent.ensure_role(
            entity_id=hh_ulid,
            role_code="resource",
            request_id=new_ulid(),
            actor_id=None,
        )

        # Org B: Acme Foundation (Sponsor)
        acme_ulid = ent.ensure_org(
            legal_name="Acme Foundation",
            doing_business_as="Acme Philanthropy",
            ein="98-7654321",
            request_id=new_ulid(),
            actor_id=None,
        )
        ent.upsert_address(
            entity_id=acme_ulid,
            purpose="mailing",
            address1="500 Charity Blvd",
            address2=None,
            city="Reno",
            state="NV",
            postal="89503",
            tz="America/Los_Angeles",
            request_id=new_ulid(),
            actor_id=None,
        )
        ent.ensure_role(
            entity_id=acme_ulid,
            role_code="sponsor",
            request_id=new_ulid(),
            actor_id=None,
        )

        print("✓ entities/person/orgs/roles created")
        return {
            "person_ulid": jane_ulid,
            "resource_ulid": hh_ulid,
            "sponsor_ulid": acme_ulid,
        }
    except Exception as e:
        print(f"• entity seeding skipped: {e}")
        return {}


def seed_customer(jane_ulid: str | None):
    if not jane_ulid or not _has_table("customer_customer"):
        print("• customer seeding skipped (missing table or person)")
        return
    try:
        from app.slices.customers import services as cust

        cust_ulid = cust.ensure_customer(entity_ulid=jane_ulid, actor_id=None)

        # Lightweight needs history entry (Tier 1 + 2 sample)
        cust.update_tier1(
            customer_ulid=cust_ulid,
            updates={
                "food": 2,
                "hygiene": 2,
                "health": 3,
                "housing": 2,
                "clothing": 2,
            },
            actor_id=None,
            happened_at_utc=utc_now(),
        )
        cust.update_tier2(
            customer_ulid=cust_ulid,
            updates={
                "income": 2,
                "employment": 2,
                "transportation": 2,
                "education": 3,
            },
            actor_id=None,
            happened_at_utc=utc_now(),
        )
        print("✓ customer + needs history seeded")
    except Exception as e:
        print(f"• customer seeding skipped: {e}")


def seed_resource(hh_ulid: str | None):
    if not hh_ulid or not _has_table("resource_resource"):
        print("• resource seeding skipped (missing table or org)")
        return
    try:
        from app.slices.resources import services as res

        res_ulid = res.ensure_resource(entity_ulid=hh_ulid, actor_id=None)

        # Minimal capability matrix (boolean + notes)
        res.upsert_capabilities(
            resource_ulid=res_ulid,
            capabilities={
                "basic_needs": {
                    "food_pantry": {"has": True, "note": "Tue/Thu 10–2"}
                },
                "events": {
                    "food_service": {"has": True, "note": "Hot meals 1x/week"}
                },
                "meta": {"unclassified": {"has": False}},
            },
            actor_id=None,
        )
        print("✓ resource + capabilities seeded")
    except Exception as e:
        print(f"• resource seeding skipped: {e}")


def seed_sponsor(acme_ulid: str | None):
    if not acme_ulid or not _has_table("sponsor_sponsor"):
        print("• sponsor seeding skipped (missing table or org)")
        return
    try:
        from app.slices.sponsors import services as sp

        sp_ulid = sp.ensure_sponsor(entity_ulid=acme_ulid, actor_id=None)
        # Optional: small pledge index / readiness, etc., if your services expose helpers
        print("✓ sponsor seeded")
    except Exception as e:
        print(f"• sponsor seeding skipped: {e}")


def main():
    app = create_app("config.DevConfig")
    with app.app_context():
        # Ensure schema exists
        db.create_all()

        seed_policies()
        refs = seed_entities()
        seed_customer(refs.get("person_ulid"))
        seed_resource(refs.get("resource_ulid"))
        seed_sponsor(refs.get("sponsor_ulid"))

        db.session.commit()
        print("=== seed complete ===")


if __name__ == "__main__":
    sys.exit(main() or 0)
