# tests/foundation/test_ledger_immutable.py
import pytest
from sqlalchemy.exc import OperationalError, IntegrityError
from app.extensions import db
from app.slices.ledger.models import LedgerEvent

def test_ledger_rows_are_immutable():
    ev = db.session.query(LedgerEvent).first()
    assert ev, "need at least one event"
    with pytest.raises((OperationalError, IntegrityError)):
        db.session.execute(db.text(
            "UPDATE ledger_event SET event_type = :x WHERE ulid = :u"
        ), {"x": "tamper", "u": ev.ulid})
        db.session.commit()
    with pytest.raises((OperationalError, IntegrityError)):
        db.session.execute(db.text(
            "DELETE FROM ledger_event WHERE ulid = :u"
        ), {"u": ev.ulid})
        db.session.commit()
