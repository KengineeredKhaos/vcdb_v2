# tests/governance/test_contract.py


def test_governance_contract_lists(app):
    # Contract should delegate to services and return simple value objects
    from app.extensions.contracts.governance import v1 as g

    states = g.get_states()
    assert isinstance(states, list)

    # Be tolerant of object or dict shape
    def _code(x):  # supports model-ish or dict-ish payloads
        return getattr(x, "code", None) or x.get("code")

    codes = {_code(s) for s in states}
    assert "CA" in codes  # California present from seeded canonicals

    roles = g.get_domain_roles()
    assert isinstance(roles, list)
    role_codes = {getattr(r, "code", None) or r.get("code") for r in roles}
    assert {"customer", "resource", "sponsor", "governor"}.issubset(
        role_codes
    )
