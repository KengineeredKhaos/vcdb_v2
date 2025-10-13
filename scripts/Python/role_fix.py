from sqlalchemy import text

from app import create_app
from app.extensions import db, ulid
from app.slices.entity.services import ensure_role

app = create_app("config.DevConfig")
with app.app_context():
    rows = db.session.execute(
        text(
            """
        SELECT p.entity_id
        FROM entity_person p
        LEFT JOIN entity_role r
          ON r.entity_id = p.entity_id AND r.role_code = 'customer'
        WHERE r.entity_id IS NULL
    """
        )
    ).fetchall()

    print("Backfilling", len(rows), "people")
    for (pid,) in rows:
        ensure_role(
            entity_id=pid,
            role_code="customer",
            request_id=f"req-backfill-customer-{ulid()}",
            actor_id=None,
        )
    print("Done.")
