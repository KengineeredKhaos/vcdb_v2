def test_finance_contract_get_fund(app):
    from app.extensions.contracts.finance import v1 as f

    assert f.get_fund("01NOPE") is None
