def test_policy_set_and_read(app):
    from app.slices.governance import services as gov

    gov.set_policy(
        "resources", "max_upload_mb", {"value": 20}, actor_ulid="01ACTOR"
    )
    v = gov.get_policy("resources", "max_upload_mb")
    assert v["value"] == 20
