# scripts/seed_auth.py (example)
from app.extensions import db
from app.slices.auth.services import create_user, assign_role, ensure_role


def run(request_id: str = "seed-auth-0001"):
    # Ensure roles
    for code in ("user", "auditor", "admin"):
        ensure_role(code)

    # Users
    admin_ulid = create_user(
        username="admin",
        password="ChangeMe123!",
        email="admin@example.local",
        entity_ulid=None,
        request_id=request_id,
        actor_id=None,
    )
    assign_role(
        user_ulid=admin_ulid,
        role_code="admin",
        request_id=request_id,
        actor_id=admin_ulid,
    )

    staff_ulid = create_user(
        username="staff",
        password="ChangeMe123!",
        email="staff@example.local",
        entity_ulid=None,
        request_id=request_id,
        actor_id=admin_ulid,
    )
    assign_role(
        user_ulid=staff_ulid,
        role_code="user",
        request_id=request_id,
        actor_id=admin_ulid,
    )

    auditor_ulid = create_user(
        username="auditor",
        password="ChangeMe123!",
        email="auditor@example.local",
        entity_ulid=None,
        request_id=request_id,
        actor_id=admin_ulid,
    )
    assign_role(
        user_ulid=auditor_ulid,
        role_code="auditor",
        request_id=request_id,
        actor_id=admin_ulid,
    )

    print("Seeded users:", admin_ulid, staff_ulid, auditor_ulid)
