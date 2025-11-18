# tests/foundation/test_poc_policy_contract.py
def test_poc_policy_contract_smoke(client):
    from app.extensions.contracts.governance_v2 import get_poc_policy

    p = get_poc_policy()
    assert "poc_scopes" in p and isinstance(p["poc_scopes"], list)
    assert p["default_scope"] in p["poc_scopes"]
    assert 0 <= p["max_rank"] <= 99
