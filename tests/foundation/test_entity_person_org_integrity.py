# tests/foundation/test_entity_person_org_integrity.py
from app.slices.entity.services import(
    create_person_entity,
    create_org_entity,
)

def test_create_person_entity_happy_path(write_session):
    dto = create_person_entity(
        first_name="Ava",
        last_name="Ng",
        preferred_name="Avianna Nogglas",
        session=write_session,
    )
    assert dto.ulid and len(dto.ulid) == 26
    assert dto.kind == "person"
    # Backrefs / timestamps
    assert dto.created_at_utc and dto.updated_at_utc

def test_create_org_entity_happy_path(write_session):
    dto = create_org_entity(
        legal_name="North Star Services",
        dba_name="NorthStarSrvs",
        session=write_session,
    )
    assert dto.ulid and len(dto.ulid) == 26
    assert dto.kind == "org"

def test_person_org_fk_backrefs(ro_session):
    # Ensure Person/Org ↔ Entity FKs and backrefs are intact
    from app.slices.entity.models import Entity, EntityPerson, EntityOrg
    e = ro_session.query(Entity).first()
    if e is None:
        # Seed should ensure ≥1 entity exists
        pytest.skip("Seeded data not present; run seed path first.")
    if e.kind == "person":
        assert isinstance(e.person, EntityPerson)
    elif e.kind == "org":
        assert isinstance(e.org, EntityOrg)
