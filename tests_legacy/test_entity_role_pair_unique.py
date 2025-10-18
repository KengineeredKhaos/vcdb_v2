def test_entity_role_pair_unique(app):
    from app.slices.entity import services as ent

    e = ent.ensure_org(legal_name="Acme")
    ent.add_role(e["ulid"], "resource")
    with app.pytest.raises(Exception):
        ent.add_role(e["ulid"], "resource")
