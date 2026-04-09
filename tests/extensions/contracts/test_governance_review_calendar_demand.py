# tests/extensions/contracts/test_governance_review_calendar_demand.py`

from app.extensions.contracts import governance_v2


DRAFT_ULID = "01J8M6Y6M7A1B2C3D4E5F6G7H8"
PROJECT_ULID = "01J8M6Y6M7H8G7F6E5D4C3B2A1"
SNAPSHOT_ULID = "01J8M6Y6M7Q1W2E3R4T5Y6U7I8"


def test_review_calendar_demand_returns_approved_package():
    req = governance_v2.GovernanceReviewRequestDTO(
        demand_draft_ulid=DRAFT_ULID,
        project_ulid=PROJECT_ULID,
        budget_snapshot_ulid=SNAPSHOT_ULID,
        requested_amount_cents=5000,
        title="Welcome Home Ask",
        summary="Kitchen, bedding, and hygiene support.",
        scope_summary="Initial move-in support.",
        needed_by_date="2026-04-15",
        source_profile_key_candidate=(
            "welcome_home_reimbursement_bridgeable"
        ),
        ops_support_planned=True,
        spending_class_candidate="basic_needs",
        tag_any=("welcome_home_kit",),
    )

    out = governance_v2.review_calendar_demand(req)

    assert out.decision == "approved"
    assert out.governance_note
    assert out.approved_spending_class == "basic_needs"
    assert out.approved_source_profile_key == (
        "welcome_home_reimbursement_bridgeable"
    )
    assert isinstance(out.eligible_fund_codes, tuple)
    assert isinstance(out.default_restriction_keys, tuple)
    assert out.approved_tag_any == ("welcome_home_kit",)
    assert out.validation_errors == ()
    assert out.decision_fingerprint


def test_review_calendar_demand_returns_revision_for_missing_title():
    req = governance_v2.GovernanceReviewRequestDTO(
        demand_draft_ulid=DRAFT_ULID,
        project_ulid=PROJECT_ULID,
        budget_snapshot_ulid=SNAPSHOT_ULID,
        requested_amount_cents=5000,
        title="",
        summary="Kitchen, bedding, and hygiene support.",
        scope_summary="Initial move-in support.",
        needed_by_date="2026-04-15",
        source_profile_key_candidate=(
            "welcome_home_reimbursement_bridgeable"
        ),
        ops_support_planned=True,
        spending_class_candidate="basic_needs",
        tag_any=("welcome_home_kit",),
    )

    out = governance_v2.review_calendar_demand(req)

    assert out.decision == "returned_for_revision"
    assert out.approved_spending_class is None
    assert out.approved_source_profile_key is None
    assert out.eligible_fund_codes == ()
    assert out.default_restriction_keys == ()
    assert out.approved_tag_any == ()
    assert out.validation_errors
    assert "title" in " ".join(out.validation_errors).lower()
