from app.extensions.contracts import finance_v2


def test_finance_v2_contract_surface_has_no_legacy_fund_wrappers():
    legacy = (
        'create_fund',
        'transfer',
        'set_budget',
        'get_fund_summary',
        'list_funds',
    )
    still_present = [name for name in legacy if hasattr(finance_v2, name)]
    assert still_present == []
