#!/usr/bin/env python3
# scripts/seed_dev.py
from __future__ import annotations

import os
import sys
from typing import Dict

from sqlalchemy import inspect

from app import create_app
from app.extensions import db
from app.lib.chrono import utc_now
from app.lib.ids import new_ulid

# ---- helpers ----------------------------------------------------------------


def _has_tables(*names: str) -> bool:
    try:
        insp = inspect(db.engine)
        existing = set(insp.get_table_names())
        return all(n in existing for n in names)
    except Exception:
        return False


def _say(msg: str):
    print(msg)


# ---- seeders ----------------------------------------------------------------


def seed_policies():
    """Bootstrap Governance defaults (via services registry)."""
    try:
        from app.slices.governance import services as gov

        for family in gov.list_policy_keys():
            gov.get_policy_value(family)  # inserts default active if missing
        _say("✓ governance policies bootstrapped")
    except Exception as e:
        _say(f"• governance skipped: {e}")


def seed_auth() -> dict[str, str]:
    """
    Ensure minimal RBAC + users.
    Returns {'admin_ulid': ..., 'staff_ulid': ..., 'auditor_ulid': ...} (existing or new).
    """
    out: dict[str, str] = {}
    if not _has_tables("auth_user", "auth_role", "auth_user_role"):
        _say("• auth seeding skipped (auth tables not present)")
        return out
    try:
        from app.slices.auth import services as auth

        # roles (strict set lives in auth.services.RBAC_ALLOWED)
        for code, desc in [
            ("admin", "Site administrator"),
            ("auditor", "Read-only reviewer"),
            ("user", "Standard user"),
        ]:
            auth.ensure_role(code, desc)

        # users (password from env with a sane dev default)
        pw = os.getenv("DEV_ADMIN_PASSWORD", "ChangeMe123!")
        admin_ulid = auth.create_user(
            username="admin",
            password=pw,
            email="admin@example.local",
            entity_ulid=None,
            request_id=new_ulid(),
            actor_ulid=None,
        )
        # idempotent role attach (returns False if already attached)
        auth.assign_role(
            user_ulid=admin_ulid,
            role_code="admin",
            request_id=new_ulid(),
            actor_ulid=admin_ulid,
        )

        staff_ulid = auth.create_user(
            username="staff",
            password=pw,
            email="staff@example.local",
            entity_ulid=None,
            request_id=new_ulid(),
            actor_ulid=admin_ulid,
        )
        auth.assign_role(
            user_ulid=staff_ulid,
            role_code="user",
            request_id=new_ulid(),
            actor_ulid=admin_ulid,
        )

        auditor_ulid = auth.create_user(
            username="auditor",
            password=pw,
            email="auditor@example.local",
            entity_ulid=None,
            request_id=new_ulid(),
            actor_ulid=admin_ulid,
        )
        auth.assign_role(
            user_ulid=auditor_ulid,
            role_code="auditor",
            request_id=new_ulid(),
            actor_ulid=admin_ulid,
        )

        db.session.commit()
        _say(
            f"✓ auth users seeded (admin={admin_ulid}, staff={staff_ulid}, auditor={auditor_ulid})"
        )
        out.update(
            {
                "admin_ulid": admin_ulid,
                "staff_ulid": staff_ulid,
                "auditor_ulid": auditor_ulid,
            }
        )
    except Exception as e:
        db.session.rollback()
        _say(f"• auth seeding failed: {e}")
    return out


def seed_entities() -> dict[str, str]:
    """
    Create one person (future customer) and two orgs (resource + sponsor).
    Returns {'person_ulid': ..., 'resource_entity_ulid': ..., 'sponsor_entity_ulid': ...}
    """
    out: dict[str, str] = {}
    if not _has_tables("entity_entity", "entity_person", "entity_org"):
        _say("• entity seeding skipped (entity tables not present)")
        return out
    try:
        from app.slices.entity import services as ent

        # Person: Jane Doe
        person_ulid = ent.ensure_person(
            first_name="Jane",
            last_name="Doe",
            email="jane@example.org",
            phone="+15555550100",  # E.164-ish; aligns with your validators
            request_id=new_ulid(),
            actor_ulid=None,
        )
        ent.upsert_address(
            entity_ulid=person_ulid,
            is_physical=True,
            is_postal=False,
            address1="123 Main St",
            address2=None,
            city="Reno",
            state="NV",
            postal_code="89501",
            request_id=new_ulid(),
            actor_ulid=None,
        )

        # Org: Helping Hands (resource)
        resource_entity_ulid = ent.ensure_org(
            legal_name="Helping Hands Community Org",
            dba_name=None,
            ein="12-3456789",
            request_id=new_ulid(),
            actor_ulid=None,
        )
        ent.upsert_address(
            entity_ulid=resource_entity_ulid,
            is_physical=True,
            is_postal=False,
            address1="200 Service Ave",
            address2="Suite 10",
            city="Reno",
            state="NV",
            postal_code="89502",
            request_id=new_ulid(),
            actor_ulid=None,
        )

        # Org: Acme Foundation (sponsor)
        sponsor_entity_ulid = ent.ensure_org(
            legal_name="Acme Foundation",
            dba_name="Acme Philanthropy",
            ein="98-7654321",
            request_id=new_ulid(),
            actor_ulid=None,
        )
        ent.upsert_address(
            entity_ulid=sponsor_entity_ulid,
            is_physical=False,
            is_postal=True,
            address1="500 Charity Blvd",
            address2=None,
            city="Reno",
            state="NV",
            postal_code="89503",
            request_id=new_ulid(),
            actor_ulid=None,
        )

        # Attach domain roles (allowed by Governance)
        ent.ensure_role(
            entity_ulid=person_ulid,
            role="customer",
            request_id=new_ulid(),
            actor_ulid=None,
        )
        ent.ensure_role(
            entity_ulid=resource_entity_ulid,
            role="resource",
            request_id=new_ulid(),
            actor_ulid=None,
        )
        ent.ensure_role(
            entity_ulid=sponsor_entity_ulid,
            role="sponsor",
            request_id=new_ulid(),
            actor_ulid=None,
        )

        db.session.commit()
        _say("✓ entities seeded (person + orgs + domain roles)")
        out.update(
            {
                "person_ulid": person_ulid,
                "resource_entity_ulid": resource_entity_ulid,
                "sponsor_entity_ulid": sponsor_entity_ulid,
            }
        )
    except Exception as e:
        db.session.rollback()
        _say(f"• entity seeding failed: {e}")
    return out


def seed_customer(person_entity_ulid: str | None):
    if not person_entity_ulid or not _has_tables(
        "customer_customer", "customer_history"
    ):
        _say("• customer seeding skipped (missing tables or person)")
        return
    try:
        from app.slices.customers import services as cust

        cust_ulid = cust.ensure_customer(
            entity_ulid=person_entity_ulid, actor_ulid=None
        )

        # A couple of history entries
        cust.update_tier1(
            customer_ulid=cust_ulid,
            updates={
                "food": 2,
                "hygiene": 2,
                "health": 3,
                "housing": 2,
                "clothing": 2,
            },
            actor_ulid=None,
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
            actor_ulid=None,
            happened_at_utc=utc_now(),
        )
        _say("✓ customer & needs history seeded")
    except Exception as e:
        _say(f"• customer seeding skipped: {e}")


def seed_resource(resource_entity_ulid: str | None):
    if not resource_entity_ulid or not _has_tables(
        "resource_resource", "resource_history", "resource_capability_index"
    ):
        _say("• resource seeding skipped (missing tables or org)")
        return
    try:
        from app.slices.resources import services as res

        res_ulid = res.ensure_resource(
            entity_ulid=resource_entity_ulid, actor_ulid=None
        )

        res.upsert_capabilities(
            resource_ulid=res_ulid,
            capabilities={
                "basic_needs": {
                    "food_pantry": {"has": True, "note": "Tue/Thu 10–2"}
                },
                "events": {
                    "food_service": {"has": True, "note": "Hot meals weekly"}
                },
                "meta": {"unclassified": {"has": False}},
            },
            actor_ulid=None,
        )
        _say("✓ resource + capabilities seeded")
    except Exception as e:
        _say(f"• resource seeding skipped: {e}")


def seed_sponsor(sponsor_entity_ulid: str | None):
    if not sponsor_entity_ulid or not _has_tables(
        "sponsor_sponsor",
        "sponsor_history",
        "sponsor_pledge_index",
        "sponsor_capability_index",
    ):
        _say("• sponsor seeding skipped (missing tables or org)")
        return
    try:
        from app.slices.sponsors import services as sp

        sp.ensure_sponsor(entity_ulid=sponsor_entity_ulid, actor_ulid=None)
        _say("✓ sponsor seeded")
    except Exception as e:
        _say(f"• sponsor seeding skipped: {e}")


# ---- main ------------------------------------------------------------------


def main() -> int:
    app = create_app("config.DevConfig")
    with app.app_context():
        # ensure all models are registered
        # from app.slices.attachments import models as _a  # noqa: F401
        from app.slices.customers import models as _c  # noqa: F401
        from app.slices.entity import models as _e  # noqa: F401
        from app.slices.resources import models as _r  # noqa: F401
        from app.slices.sponsors import models as _s  # noqa: F401

        # ensure schema exists for whatever is currently imported
        db.create_all()

        seed_policies()
        auth_refs = seed_auth()
        ent_refs = seed_entities()
        seed_customer(ent_refs.get("person_ulid"))
        seed_resource(ent_refs.get("resource_entity_ulid"))
        seed_sponsor(ent_refs.get("sponsor_entity_ulid"))

        # one final commit (most services commit internally; this is just belt & suspenders)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        _say("=== seed complete ===")
        return 0


if __name__ == "__main__":
    sys.exit(main())
