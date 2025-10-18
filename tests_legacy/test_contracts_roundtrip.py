from app.slices.governance import services as gov


def test_contract_dump_active_and_set(app):
    # Ensure we can dump current active policies to a serializable payload
    dumped = gov.dump_active()
    assert isinstance(dumped, dict)
    assert "governance.roles" in dumped

    # Mutate a policy via services, then dump again and see the change
    gov.set_policy(
        namespace="governance",
        key="roles",
        value={"roles": ["customer", "resource", "sponsor"]},
        actor_entity_ulid=None,
    )
    dumped2 = gov.dump_active()
    assert dumped2["governance.roles"]["value"]["roles"] == [
        "customer",
        "resource",
        "sponsor",
    ]
