from app.slices.logistics.qualifiers import evaluate
from app.extensions.contracts.customers_v2 import CustomerCuesDTO


def cues(**kw) -> CustomerCuesDTO:
    base = dict(
        customer_ulid="01TESTCUES000000000000000000",
        tier1_min=None,
        tier2_min=None,
        tier3_min=None,
        is_veteran_verified=False,
        is_homeless_verified=False,
        flag_tier1_immediate=False,
        watchlist=False,
        watchlist_since_utc=None,
        as_of_iso="2026-01-28T00:00:00.000Z",
    )
    base.update(kw)
    return CustomerCuesDTO(**base)


def test_empty_qualifiers_allows():
    out = evaluate(qualifiers={}, customer_cues=None)
    assert out.ok is True
    assert out.reason is None


def test_veteran_required_passes_when_verified():
    out = evaluate(
        qualifiers={"veteran_required": True},
        customer_cues=cues(is_veteran_verified=True),
    )
    assert out.ok is True


def test_veteran_required_fails_closed_when_missing_cues():
    out = evaluate(
        qualifiers={"veteran_required": True},
        customer_cues=None,
    )
    assert out.ok is False
    assert out.reason == "veteran_required"


def test_unknown_truthy_qualifier_denies():
    out = evaluate(
        qualifiers={"some_new_switch": True},
        customer_cues=cues(),
    )
    assert out.ok is False
    assert out.reason.startswith("unknown_qualifier:")


def test_bad_type_for_known_key_denies():
    # Policy bug: known key but wrong type should fail closed.
    out = evaluate(
        qualifiers={"tier1_min_at_least": "2"},
        customer_cues=cues(tier1_min=3),
    )
    assert out.ok is False
    assert out.reason == "bad_qualifier_value:tier1_min_at_least"
