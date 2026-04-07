from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

ACCEPTANCE_STATUSES = (
    "pending",
    "accepted",
    "declined",
    "withdrawn",
)

GRANT_FUNDING_MODES = (
    "advance",
    "reimbursement",
)

GRANT_REPORTING_FREQUENCIES = (
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "end_of_term",
)


class GrantAcceptanceForm(FlaskForm):
    sponsor_ulid = StringField(
        "Sponsor ULID",
        validators=[DataRequired(), Length(min=26, max=26)],
    )
    is_grant_award = BooleanField("This acceptance creates a grant")
    acceptance_status = SelectField(
        "Acceptance status",
        choices=[
            (value, value.replace("_", " ").title())
            for value in ACCEPTANCE_STATUSES
        ],
        validators=[DataRequired()],
    )
    accepted_on = DateField("Accepted on", validators=[DataRequired()])
    award_name = StringField(
        "Award name",
        validators=[DataRequired(), Length(max=160)],
    )
    award_number = StringField(
        "Award number",
        validators=[Optional(), Length(max=64)],
    )
    amount_offered_cents = IntegerField(
        "Amount offered (cents)",
        validators=[DataRequired(), NumberRange(min=1)],
    )
    offer_reference = StringField(
        "Offer reference",
        validators=[Optional(), Length(max=255)],
    )
    purpose_summary = TextAreaField(
        "Purpose summary",
        validators=[Optional(), Length(max=2000)],
    )
    conditions_summary = TextAreaField(
        "Conditions summary",
        validators=[Optional(), Length(max=2000)],
    )
    source_document_ref = StringField(
        "Source document ref",
        validators=[Optional(), Length(max=255)],
    )
    sponsor_contact_ref = StringField(
        "Sponsor contact ref",
        validators=[Optional(), Length(max=255)],
    )
    award_start_on = DateField("Award start", validators=[Optional()])
    award_end_on = DateField("Award end", validators=[Optional()])
    project_ulid = StringField(
        "Calendar project ULID",
        validators=[Optional(), Length(min=26, max=26)],
    )
    notes = TextAreaField(
        "Notes",
        validators=[Optional(), Length(max=4000)],
    )

    fund_code = StringField(
        "Fund code",
        validators=[Optional(), Length(max=32)],
    )
    restriction_type = SelectField(
        "Restriction type",
        choices=[],
        validators=[Optional()],
    )
    funding_mode = SelectField(
        "Funding mode",
        choices=[(value, value.title()) for value in GRANT_FUNDING_MODES],
        validators=[Optional()],
    )
    reporting_frequency = SelectField(
        "Reporting frequency",
        choices=[
            (value, value.replace("_", " ").title())
            for value in GRANT_REPORTING_FREQUENCIES
        ],
        validators=[Optional()],
    )
    allowable_expense_kinds_csv = StringField(
        "Allowable expense kinds",
        validators=[Optional(), Length(max=1000)],
    )
    match_required_cents = IntegerField(
        "Match required (cents)",
        validators=[Optional(), NumberRange(min=0)],
    )
    program_income_allowed = BooleanField("Program income allowed")

    submit = SubmitField("Save acceptance")

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False

        if self.award_start_on.data and self.award_end_on.data:
            if self.award_end_on.data < self.award_start_on.data:
                self.award_end_on.errors.append(
                    "Award end date cannot be before start date."
                )
                ok = False

        if self.is_grant_award.data:
            required_when_grant = (
                self.fund_code,
                self.restriction_type,
                self.funding_mode,
                self.reporting_frequency,
            )
            for field in required_when_grant:
                if not str(field.data or "").strip():
                    field.errors.append("Required for grant awards.")
                    ok = False
        return ok
