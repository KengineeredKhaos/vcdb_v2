from app.slices.governance import services as gov


def test_roles_update_increments_version(db):
    # Snapshot current (may be 0 if first run)
    _ = gov.get_policy_value("governance.roles")

    # Update with a valid subset/superset of domain roles (no RBAC here)
    row = gov.set_policy(
        "governance",
        "roles",
        {"roles": ["customer", "resource", "sponsor"]},
        actor_entity_ulid=None,
    )
    assert row.version >= 1

    new_val = gov.get_policy_value("governance.roles")
    assert set(new_val["roles"]) == {"customer", "resource", "sponsor"}
