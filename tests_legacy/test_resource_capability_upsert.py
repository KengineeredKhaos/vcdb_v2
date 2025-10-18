def test_resource_capability_upsert(app):
    from app.slices.resources import services as res

    r = res.ensure_resource(entity_ulid="01R")
    res.upsert_capability(
        r["ulid"], domain="facilities", key="beds", active=True
    )
    res.upsert_capability(
        r["ulid"], domain="facilities", key="beds", active=False
    )
    caps = res.list_capabilities(r["ulid"])
    assert any(c["key"] == "beds" for c in caps)
