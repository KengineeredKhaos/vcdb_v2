# app/seeder/seed_ulid_minimal.py
import json
from app import create_app, db
from app.lib.ids import new_ulid
from app.slices.entity.models import Entity, EntityRole
from app.slices.governance.models import Policy, CapabilityGrant

DOMAIN_ROLES_KEY = "entity.domain_roles"


def run():
    app = create_app("config.DevConfig")
    with app.app_context():
        db.drop_all()
        db.create_all()

        # policy: only domain roles here (RBAC lives in auth slice)
        db.session.add(
            Policy(
                key=DOMAIN_ROLES_KEY,
                value_json=json.dumps(["customer", "resource", "sponsor"]),
            )
        )

        # sample entities
        gov = Entity(ulid=new_ulid(), display_name="Board Chair")
        alice = Entity(ulid=new_ulid(), display_name="Alice Customer")
        bob = Entity(ulid=new_ulid(), display_name="Bob Resource")
        sally = Entity(ulid=new_ulid(), display_name="Sally Sponsor")
        db.session.add_all([gov, alice, bob, sally])

        # domain roles
        db.session.add_all(
            [
                EntityRole(entity_ulid=alice.ulid, role="customer"),
                EntityRole(entity_ulid=bob.ulid, role="resource"),
                EntityRole(entity_ulid=sally.ulid, role="sponsor"),
            ]
        )

        # capability: governance power (not RBAC)
        db.session.add(
            CapabilityGrant(principal_ulid=gov.ulid, capability="governor")
        )

        db.session.commit()
        print(
            "Seeded:",
            {
                "gov": gov.ulid,
                "alice": alice.ulid,
                "bob": bob.ulid,
                "sally": sally.ulid,
            },
        )


if __name__ == "__main__":
    run()
