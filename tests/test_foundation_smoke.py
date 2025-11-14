# tests/test_foundation_smoke.py
def test_foundation_smoke(app):
    from app.extensions import db
    from app.slices.entity.models import Entity, EntityPerson, EntityOrg
    from app.slices.customers.models import Customer
    from app.slices.resources.models import Resource
    from app.slices.sponsors.models import Sponsor


    assert db.session.query(Entity).count() > 0
    assert db.session.query(EntityPerson).count() > 0
    assert db.session.query(EntityOrg).count() > 0
    assert db.session.query(Customer).count() > 0
    assert db.session.query(Resource).count() > 0
    assert db.session.query(Sponsor).count() > 0
