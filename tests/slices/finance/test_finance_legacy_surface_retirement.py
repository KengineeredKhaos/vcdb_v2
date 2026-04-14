from app.extensions.contracts import finance_v2
from app.extensions.errors import ContractError
import pytest


@pytest.mark.parametrize(
    ("name", "call"),
    [
        (
            "log_donation",
            lambda: finance_v2.log_donation(
                sponsor_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                fund_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                happened_at_utc="2026-04-14T00:00:00Z",
                amount_cents=100,
            ),
        ),
        (
            "preview_expense",
            lambda: finance_v2.preview_expense(
                fund_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                project_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                fund_archetype_key="general",
                project_type_key=None,
                amount_cents=100,
            ),
        ),
        (
            "log_expense",
            lambda: finance_v2.log_expense(
                fund_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                project_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                happened_at_utc="2026-04-14T00:00:00Z",
                vendor="Vendor",
                amount_cents=100,
                category="event_food",
            ),
        ),
        (
            "record_receipt",
            lambda: finance_v2.record_receipt({}),
        ),
    ],
)
def test_finance_v2_legacy_surfaces_are_retired(name, call):
    with pytest.raises(ContractError) as exc:
        call()
    assert exc.value.code == "retired"
    assert exc.value.http_status == 410
    assert name in exc.value.where


def test_finance_v2_public_surface_excludes_legacy_money_wrappers():
    retired = {
        "log_donation",
        "preview_expense",
        "log_expense",
        "record_receipt",
    }
    assert retired.isdisjoint(set(finance_v2.__all__))
