# scripts/Python/seed_minimal.py
from __future__ import annotations

from app import create_app
from app.extensions import allowed_role_codes, db, entity_api, ulid

# ---- Config for the seed ----
PERSON = {
    "first_name": "Dev",
    "last_name": "User",
    "email": "dev@example.org",
    "phone": "5551234567",
    "roles": ("staff",),  # attach to the person
}

ORG = {
    "legal_name": "Vet Connect",
    "doing_business_as": "VCDB",
    "ein": "123-45-6789",  # normalized by service
    "roles": ("resource", "sponsor"),  # attach to the org
}

ADDRESS = {
    "purpose": "physical",
    "address1": "123 Demo St",
    "city": "Springfield",
    "state": "CA",  # your app expects 2-letter codes
    "postal": "90210",
    "tz": "America/Los_Angeles",
}


def main():
    app = create_app("config.DevConfig")
    with app.app_context():
        req_id = ulid()
        actor = ulid()

        # 1) Person (idempotent on primary contact)
        person_id = entity_api.ensure_person(
            first_name=PERSON["first_name"],
            last_name=PERSON["last_name"],
            email=PERSON["email"],
            phone=PERSON["phone"],
            request_id=req_id,
            actor_ulid=actor,
        )

        # 2) Org (idempotent on EIN if provided)
        org_id = entity_api.ensure_org(
            legal_name=ORG["legal_name"],
            doing_business_as=ORG["doing_business_as"],
            ein=ORG["ein"],
            request_id=req_id,
            actor_ulid=actor,
        )

        # 3) Optional address on org (works for person too)
        entity_api.upsert_address(
            entity_id=org_id,
            purpose=ADDRESS["purpose"],
            address1=ADDRESS["address1"],
            address2=None,
            city=ADDRESS["city"],
            state=ADDRESS["state"],
            postal=ADDRESS["postal"],
            tz=ADDRESS["tz"],
            request_id=req_id,
            actor_ulid=actor,
        )

        # 4) Roles (respect governance policy)
        allowed = set(allowed_role_codes())
        for rc in PERSON["roles"]:
            if rc in allowed:
                entity_api.ensure_role(
                    entity_id=person_id,
                    role_code=rc,
                    request_id=req_id,
                    actor_ulid=actor,
                )

        for rc in ORG["roles"]:
            if rc in allowed:
                entity_api.ensure_role(
                    entity_id=org_id,
                    role_code=rc,
                    request_id=req_id,
                    actor_ulid=actor,
                )

        db.session.commit()

        print("Seed complete.")
        print("  person_id:", person_id)
        print("  org_id   :", org_id)


if __name__ == "__main__":
    main()
