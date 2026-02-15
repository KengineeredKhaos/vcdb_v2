# app/slices/entity/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Length
from wtforms.validators import Optional as Opt

from app.lib.utils import normalize_dob, validate_dob


class PersonCoreForm(FlaskForm):
    first_name = StringField(
        "First name",
        validators=[
            DataRequired(message="First name is required"),
            Length(max=80),
        ],
    )
    last_name = StringField(
        "Last name",
        validators=[
            DataRequired(message="Last name is required"),
            Length(max=80),
        ],
    )
    preferred_name = StringField(
        "Preferred name",
        validators=[Opt(), Length(max=80)],
    )
    dob = StringField(
        "DOB (YYYY-MM-DD)",
        validators=[Opt(), Length(max=10)],
    )
    last_4 = StringField(
        "SSN last 4",
        validators=[Opt(), Length(max=4)],
    )

    def validate_dob(self, field) -> None:
        raw = (field.data or "").strip()
        if not raw:
            return
        norm = normalize_dob(raw)
        if not norm or not validate_dob(norm):
            raise ValueError("Invalid DOB (use YYYY-MM-DD)")

    def validate_last_4(self, field) -> None:
        raw = (field.data or "").strip()
        if not raw:
            return
        if (not raw.isdigit()) or len(raw) != 4:
            raise ValueError("Last 4 must be exactly 4 digits")
