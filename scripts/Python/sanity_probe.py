# sanity_probe.py
from app import create_app

app = create_app("config.DevConfig")
with app.app_context():
    from app.extensions import entity_read

    print(
        "Has list_people_with_role:",
        hasattr(entity_read, "_impl")
        and "list_people_with_role" in entity_read._impl,
    )
    from flask import current_app

    print("Blueprints:", sorted(current_app.blueprints.keys()))
