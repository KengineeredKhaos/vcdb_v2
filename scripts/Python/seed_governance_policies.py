# scripts/seed_governance_policies.py (example)
from app import create_app
from app.slices.governance.models import db
from app.slices.governance.services import set_policy

ERA_DEFAULT = {
    "era": [
        "korea",
        "vietnam",
        "coldwar",
        "lebanon-grenada-panama",
        "bosnia-herz",
        "persian-gulf",
        "iraq",
        "afghanistan",
        "africa",
    ]
}

BOS_DEFAULT = {"bos": ["USA", "USMC", "USN", "USAF", "USCG", "USSF"]}

LOCALE_DEFAULT = {
    "locale": [
        "Lakeport",
        "Upper Lake",
        "Nice",
        "Lucerne",
        "Oaks",
        "Clearlake",
        "Lower Lake",
        "Middletown",
        "Cobb",
        "Blue Lakes",
        "Scotts Valley",
    ]
}

ROLES_DEFAULT = {"roles": ["customer", "resource", "sponsor", "governor"]}


def main():
    app = create_app()
    with app.app_context():
        set_policy("governance", "era", ERA_DEFAULT, actor_entity_ulid=None)
        set_policy(
            "governance", "roles", ROLES_DEFAULT, actor_entity_ulid=None
        )
        set_policy(
            "governance", "locale", LOCALE_DEFAULT, actor_entity_ulid=None
        )
        set_policy("governance", "bos".BOS_DEFAULT, actor_entity_ulid=None)


if __name__ == "__main__":
    main()
