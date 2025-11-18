# tsets/foundation/test_poc_emit_and_list.py
def test_resources_poc_link_list_emit(client, ro_session):
    from app.slices.resources.services_poc import link_poc, list_pocs
    from app.slices.entity.models import EntityOrg, EntityPerson
    from app.extensions import db

    # grab any existing seeded org/person
    org = ro_session.query(EntityOrg).first()
    person = ro_session.query(EntityPerson).first()
    assert org and person

    # ACT: link
    link_poc(
        db.session,
        org_ulid=org.entity_ulid,
        person_entity_ulid=person.entity_ulid,
        scope=None,
        rank=0,
        is_primary=True,
    )
    db.session.commit()

    # ASSERT: list returns the linkage
    items = list_pocs(ro_session, org_ulid=org.entity_ulid)
    assert any(i["person_entity_ulid"] == person.entity_ulid for i in items)
