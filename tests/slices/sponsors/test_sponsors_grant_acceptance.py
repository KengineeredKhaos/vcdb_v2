from __future__ import annotations

from datetime import date

from werkzeug.datastructures import MultiDict

from app.slices.sponsors.forms_grant_acceptance import GrantAcceptanceForm
from app.slices.sponsors.services_grant_acceptance import (
    GrantAcceptanceDTO,
    create_finance_grant,
    to_create_grant_payload,
)


def test_grant_acceptance_form_allows_non_grant_branch(app):
    with app.app_context():
        form = GrantAcceptanceForm(
            formdata=MultiDict(
                {
                    "sponsor_ulid": "01TESTTESTTESTTESTTESTTEST",
                    "acceptance_status": "accepted",
                    "accepted_on": "2026-04-03",
                    "award_name": "General Donation",
                    "amount_offered_cents": "2500",
                }
            ),
            meta={"csrf": False},
        )
        form.restriction_type.choices = [
            ("unrestricted", "Unrestricted"),
            ("temporarily_restricted", "Temporarily Restricted"),
        ]

        assert form.validate() is True


def test_grant_acceptance_form_requires_finance_fields_when_grant(app):
    with app.app_context():
        form = GrantAcceptanceForm(
            formdata=MultiDict(
                {
                    "sponsor_ulid": "01TESTTESTTESTTESTTESTTEST",
                    "is_grant_award": "y",
                    "acceptance_status": "accepted",
                    "accepted_on": "2026-04-03",
                    "award_name": "Welcome Home Grant",
                    "amount_offered_cents": "40000",
                }
            ),
            meta={"csrf": False},
        )
        form.restriction_type.choices = [
            ("unrestricted", "Unrestricted"),
            ("temporarily_restricted", "Temporarily Restricted"),
        ]

        assert form.validate() is False
        assert form.fund_code.errors
        assert form.restriction_type.errors
        assert form.funding_mode.errors
        assert form.reporting_frequency.errors


def test_to_create_grant_payload_normalizes_optional_fields():
    dto = GrantAcceptanceDTO(
        sponsor_ulid="01TESTTESTTESTTESTTESTTEST",
        is_grant_award=True,
        acceptance_status="accepted",
        accepted_on=date(2026, 4, 3),
        award_name="Welcome Home Grant",
        amount_offered_cents=40000,
        award_number="ELKS-2026-01",
        award_start_on=date(2026, 4, 5),
        project_ulid="01PROJECTTESTTESTTESTTESTTS",
        fund_code="welcome_home_elks",
        restriction_type="temporarily_restricted",
        funding_mode="reimbursement",
        reporting_frequency="end_of_term",
        allowable_expense_kinds_csv="food, housewares, food",
        match_required_cents=0,
        program_income_allowed=False,
        conditions_summary="Up to $400 per kit.",
        source_document_ref="award-letter.pdf",
        notes="pilot",
    )

    payload = to_create_grant_payload(dto)
    assert payload.start_on == "2026-04-05"
    assert payload.end_on == "2026-04-05"
    assert payload.allowable_expense_kinds == ("food", "housewares")
    assert payload.project_ulid == "01PROJECTTESTTESTTESTTESTTS"


def test_create_finance_grant_calls_finance_contract(monkeypatch):
    calls: list[dict] = []

    def fake_create_grant_award(payload):
        calls.append(payload)
        return {"id": "01GRANTTESTTESTTESTTESTTEST"}

    monkeypatch.setattr(
        "app.extensions.contracts.finance_v2.create_grant_award",
        fake_create_grant_award,
    )

    dto = GrantAcceptanceDTO(
        sponsor_ulid="01TESTTESTTESTTESTTESTTEST",
        is_grant_award=True,
        acceptance_status="accepted",
        accepted_on=date(2026, 4, 3),
        award_name="Welcome Home Grant",
        amount_offered_cents=40000,
        award_start_on=date(2026, 4, 5),
        award_end_on=date(2026, 5, 31),
        project_ulid="01PROJECTTESTTESTTESTTESTTS",
        fund_code="welcome_home_elks",
        restriction_type="temporarily_restricted",
        funding_mode="reimbursement",
        reporting_frequency="end_of_term",
        allowable_expense_kinds_csv="food, housewares",
        source_document_ref="award-letter.pdf",
    )

    out = create_finance_grant(
        dto,
        actor_ulid="01ACTORTESTTESTTESTTESTTST",
        request_id="req-grant-accept",
    )

    assert out["id"] == "01GRANTTESTTESTTESTTESTTEST"
    assert len(calls) == 1
    sent = calls[0]
    assert sent["award_name"] == "Welcome Home Grant"
    assert sent["fund_code"] == "welcome_home_elks"
    assert sent["project_ulid"] == "01PROJECTTESTTESTTESTTESTTS"
    assert sent["allowable_expense_kinds"] == ["food", "housewares"]
    assert sent["status"] == "active"
