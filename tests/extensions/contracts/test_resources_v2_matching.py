##tests/extensions/contracts/test_resources_v2_matching.py

from __future__ import annotations

from app.extensions.contracts import resources_v2
from app.extensions.errors import ContractError
from app.slices.resources import services_matching as match_svc


def test_match_customer_need_contract_shapes_result(app, monkeypatch):
    result = match_svc.ResourceNeedMatchResultView(
        customer_ulid="01CUSTOMERCUSTOMERCUSTOMER01",
        need_key="food",
        tier=1,
        tier_priority=1,
        customer_gate="allowed",
        blocked_reason=None,
        operator_cautions=("tier_immediate",),
        exact_matches=(
            match_svc.ResourceNeedMatchItemView(
                entity_ulid="01RESOURCEAAAAAAAAAAAAAAA1",
                readiness_status="active",
                mou_status="active",
                matched_capability_keys=("basic_needs.food_pantry",),
                bucket="exact",
                reason_codes=("capability_exact",),
            ),
        ),
        adjacent_matches=(),
        review_matches=(),
        as_of_iso="2026-04-04T10:00:00.000Z",
    )

    monkeypatch.setattr(
        match_svc, "match_customer_need", lambda **kwargs: result
    )

    out = resources_v2.match_customer_need(
        customer_ulid="01CUSTOMERCUSTOMERCUSTOMER01",
        need_key="food",
    )

    assert out["customer_gate"] == "allowed"
    assert out["need_key"] == "food"
    assert out["operator_cautions"] == ["tier_immediate"]
    assert (
        out["exact_matches"][0]["entity_ulid"] == "01RESOURCEAAAAAAAAAAAAAAA1"
    )
    assert out["exact_matches"][0]["matched_capability_keys"] == [
        "basic_needs.food_pantry"
    ]


def test_match_customer_need_contract_normalizes_bad_argument(
    app, monkeypatch
):
    def boom(**kwargs):
        raise ValueError("unknown need_key")

    monkeypatch.setattr(match_svc, "match_customer_need", boom)

    try:
        resources_v2.match_customer_need(
            customer_ulid="01CUSTOMERCUSTOMERCUSTOMER01",
            need_key="bogus",
        )
        raise AssertionError("expected ContractError")
    except ContractError as exc:
        assert exc.code == "bad_argument"
        assert exc.http_status == 400
