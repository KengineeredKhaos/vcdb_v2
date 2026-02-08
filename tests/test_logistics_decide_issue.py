from app.slices.logistics.issuance_services import IssueContext, decide_issue


def _policy_for_sku(sku: str, qualifiers: dict | None = None) -> dict:
    return {
        "issuance": {
            "default_behavior": "allow",
            "defaults": {"cadence": {}},
        },
        "sku_constraints": {
            "defaults": {"cadence": {}},
            "rules": [
                {
                    "match": {"sku": sku},
                    "qualifiers": qualifiers or {},
                    "cadence": {},  # no cadence limit in these tests
                }
            ],
        },
    }


def test_decide_issue_blocks_when_qualifier_not_met(monkeypatch):
    import app.slices.logistics.issuance_services as iss

    # NOTE: issuance_class must be one of [V,H,D,U] per sku.py;
    # choose V so qualifiers pipeline runs (U would bypass qualifiers).
    sku = "AC-GL-LC-L-LB-V-00B"

    monkeypatch.setattr(
        iss,
        "load_policy_logistics_issuance",
        lambda: _policy_for_sku(sku, {"veteran_required": True}),
    )

    # No blackout
    import app.extensions.enforcers as enforcers

    monkeypatch.setattr(
        enforcers, "calendar_blackout_ok", lambda ctx: (True, {})
    )

    # Avoid DB coupling in cadence for this unit test
    monkeypatch.setattr(
        iss, "_apply_cadence", lambda rule, ctx: (True, None, None)
    )

    # Provide cues via contract shim
    from app.extensions.contracts.customers_v2 import CustomerCuesDTO

    monkeypatch.setattr(
        iss,
        "get_customer_cues",
        lambda customer_ulid: CustomerCuesDTO(
            customer_ulid=customer_ulid,
            tier1_min=None,
            tier2_min=None,
            tier3_min=None,
            is_veteran_verified=False,  # <-- not met
            is_homeless_verified=False,
            flag_tier1_immediate=False,
            watchlist=False,
            watchlist_since_utc=None,
            as_of_iso="2026-01-28T00:00:00.000Z",
        ),
    )

    ctx = IssueContext(
        customer_ulid="01CUST00000000000000000000", sku_code=sku
    )
    d = decide_issue(ctx)
    assert d.allowed is False
    assert "veteran_required" in (d.reason or "")


def test_decide_issue_allows_when_qualifier_met(monkeypatch):
    import app.slices.logistics.issuance_services as iss

    sku = "AC-GL-LC-L-LB-V-00B"

    monkeypatch.setattr(
        iss,
        "load_policy_logistics_issuance",
        lambda: _policy_for_sku(sku, {"veteran_required": True}),
    )

    import app.extensions.enforcers as enforcers

    monkeypatch.setattr(
        enforcers, "calendar_blackout_ok", lambda ctx: (True, {})
    )

    monkeypatch.setattr(
        iss, "_apply_cadence", lambda rule, ctx: (True, None, None)
    )

    from app.extensions.contracts.customers_v2 import CustomerCuesDTO

    monkeypatch.setattr(
        iss,
        "get_customer_cues",
        lambda customer_ulid: CustomerCuesDTO(
            customer_ulid=customer_ulid,
            tier1_min=None,
            tier2_min=None,
            tier3_min=None,
            is_veteran_verified=True,  # <-- met
            is_homeless_verified=False,
            flag_tier1_immediate=False,
            watchlist=False,
            watchlist_since_utc=None,
            as_of_iso="2026-01-28T00:00:00.000Z",
        ),
    )

    ctx = IssueContext(
        customer_ulid="01CUST00000000000000000000", sku_code=sku
    )
    d = decide_issue(ctx)
    assert d.allowed is True
