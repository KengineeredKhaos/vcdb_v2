# tests/test_governance_smoke.py
from app.slices.governance.models import CanonicalState, RoleCode


def test_canonicals_seeded(app):
    assert CanonicalState.query.count() >= 50
    got = {r.code for r in RoleCode.query.all()}
    assert {"customer", "resource", "sponsor", "governor"} <= got
