# app/slices/sponsors/forms_funding.py

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class SponsorFundingIntentForm(FlaskForm):
    sponsor_entity_ulid = SelectField(
        "Sponsor",
        choices=[],
        validators=[DataRequired()],
    )

    funding_demand_ulid = StringField(
        "Funding Demand ULID",
        validators=[DataRequired(), Length(min=26, max=26)],
    )

    intent_kind = SelectField(
        "Intent kind",
        choices=[
            ("pledge", "pledge"),
            ("donation", "donation"),
            ("pass_through", "pass_through"),
        ],
        validators=[DataRequired()],
    )

    amount_cents = IntegerField(
        "Amount (cents)",
        validators=[DataRequired(), NumberRange(min=0)],
    )

    status = SelectField(
        "Status",
        choices=[
            ("draft", "draft"),
            ("committed", "committed"),
            ("withdrawn", "withdrawn"),
            ("fulfilled", "fulfilled"),
        ],
        validators=[DataRequired()],
    )

    note = TextAreaField(
        "Note",
        validators=[Optional(), Length(max=255)],
    )
