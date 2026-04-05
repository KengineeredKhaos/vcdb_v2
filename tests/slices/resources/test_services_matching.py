# tests/slices/resources/test_services_matching.py

from __future__ import annotations

from app.extensions.contracts.customers_v2 import CustomerCuesDTO
from app.slices.resources import services_matching as svc
from app.slices.resources.mapper import ResourceCapabilityView, ResourceView


def _view(entity_ulid: str, *caps: str) -> ResourceView:
    active = []
    for flat in caps:
        domain, key = flat.split(".", 1)
        active.append(ResourceCapabilityView(domain=domain, key=key))
    return ResourceView(
        entity_ulid=entity_ulid,
        onboard_step="complete",
        admin_review_required=False,
        readiness_status="active",
        mou_status="active",
        active_capabilities=active,
        capability_last_update_utc=None,
        first_seen_utc=None,
        last_touch_utc=None,
        created_at_utc=None,
        updated_at_utc=None,
    )


def _cues(**overrides) -> CustomerCuesDTO:
    data = dict(
        entity_ulid="01CUSTOMERCUSTOMERCUSTOMER01",
        eligibility_complete=True,
        entity_package_incomplete=False,
        is_veteran_verified=True,
        is_homeless_verified=False,
        veteran_method="dd214",
        housing_status="housed",
        tier1_unlocked=True,
        tier2_unlocked=True,
        tier3_unlocked=True,
        tier1_min=1,
        tier2_min=2,
        tier3_min=3,
        flag_tier1_immediate=False,
        watchlist=False,
        status="active",
        intake_step="complete",
        as_of_iso="2026-04-04T10:00:00.000Z",
    )
    data.update(overrides)
    return CustomerCuesDTO(**data)


def test_match_customer_need_blocks_when_customer_not_eligible(
    app, monkeypatch
):
    monkeypatch.setattr(
        svc.customers_v2,
        "get_customer_cues",
        lambda customer_ulid: _cues(eligibility_complete=False),
    )

    result = svc.match_customer_need(
        customer_ulid="01CUSTOMERCUSTOMERCUSTOMER01",
        need_key="food",
    )

    assert result.customer_gate == "blocked"
    assert result.blocked_reason == "customer_not_eligible"
    assert result.exact_matches == ()
    assert result.adjacent_matches == ()
    assert result.review_matches == ()


def test_match_customer_need_blocks_when_tier_not_unlocked(app, monkeypatch):
    monkeypatch.setattr(
        svc.customers_v2,
        "get_customer_cues",
        lambda customer_ulid: _cues(tier2_unlocked=False),
    )

    result = svc.match_customer_need(
        customer_ulid="01CUSTOMERCUSTOMERCUSTOMER01",
        need_key="employment",
    )

    assert result.customer_gate == "blocked"
    assert result.blocked_reason == "tier_not_unlocked"


def test_match_customer_need_buckets_and_dedupes_by_precedence(
    app, monkeypatch
):
    exact_view = _view(
        "01EXACTEXACTEXACTEXACTEXA1",
        "health_wellness.dental",
        "transportation.medical_transport",
    )
    adjacent_view = _view(
        "01ADJADJADJADJADJADJADJA1",
        "transportation.medical_transport",
    )
    review_view = _view(
        "01REVIEWREVIEWREVIEWREV01",
        "counseling_services.domestic_violence",
    )

    monkeypatch.setattr(
        svc.customers_v2,
        "get_customer_cues",
        lambda customer_ulid: _cues(
            entity_package_incomplete=True, watchlist=True
        ),
    )

    def fake_find_resources(**kwargs):
        any_of = tuple(kwargs.get("any_of") or ())
        if ("health_wellness", "dental") in any_of:
            return [exact_view], 1
        if ("transportation", "medical_transport") in any_of:
            return [exact_view, adjacent_view], 2
        if ("counseling_services", "domestic_violence") in any_of:
            return [review_view], 1
        return [], 0

    monkeypatch.setattr(
        svc.resource_svc, "find_resources", fake_find_resources
    )

    result = svc.match_customer_need(
        customer_ulid="01CUSTOMERCUSTOMERCUSTOMER01",
        need_key="health",
    )

    assert result.customer_gate == "allowed"
    assert result.blocked_reason is None
    assert result.tier == 1
    assert result.tier_priority == 1
    assert "entity_package_incomplete" in result.operator_cautions
    assert "customer_watchlist" in result.operator_cautions

    assert [r.entity_ulid for r in result.exact_matches] == [
        exact_view.entity_ulid
    ]
    assert result.exact_matches[0].matched_capability_keys == (
        "health_wellness.dental",
    )

    assert [r.entity_ulid for r in result.adjacent_matches] == [
        adjacent_view.entity_ulid
    ]
    assert result.adjacent_matches[0].matched_capability_keys == (
        "transportation.medical_transport",
    )

    assert [r.entity_ulid for r in result.review_matches] == [
        review_view.entity_ulid
    ]
    assert result.review_matches[0].reason_codes == (
        "capability_review_only",
    )
