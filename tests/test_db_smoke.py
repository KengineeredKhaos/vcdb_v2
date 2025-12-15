# test/test_db_smoke.py

from app.extensions import db
from app.slices.finance.models import Fund


def test_db_smoke_create_fund():
    f = Fund(code="TEST", name="Test Fund")
    db.session.add(f)
    db.session.commit()

    fetched = db.session.get(Fund, f.ulid)
    assert fetched is not None
    assert fetched.code == "TEST"
