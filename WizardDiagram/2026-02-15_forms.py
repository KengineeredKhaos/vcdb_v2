# app/slices/entity/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, StringField
from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    Optional,
    Regexp,
    ValidationError,
)

from app.lib.utils import normalize_dob, validate_dob


class PersonCoreForm(FlaskForm):
    first_name = StringField(
        "First name",
        validators=[
            DataRequired(message="First name is required"),
            Length(max=40),
        ],
    )
    last_name = StringField(
        "Last name",
        validators=[
            DataRequired(message="Last name is required"),
            Length(max=60),
        ],
    )
    preferred_name = StringField(
        "Preferred name",
        validators=[Optional(), Length(max=60)],
    )
    dob = StringField(
        "DOB (YYYY-MM-DD)",
        validators=[Optional(), Length(max=10)],
    )
    last_4 = StringField(
        "SSN last 4 digits",
        validators=[Optional(), Length(max=4)],
    )

    def validate_dob(self, field) -> None:
        raw = (field.data or "").strip()
        if not raw:
            return
        norm = normalize_dob(raw)
        if not norm or not validate_dob(norm):
            raise ValidationError("Invalid DOB (use YYYY-MM-DD)")

    def validate_last_4(self, field) -> None:
        raw = (field.data or "").strip()
        if not raw:
            return
        if (not raw.isdigit()) or len(raw) != 4:
            raise ValidationError("Last 4 must be exactly 4 digits")


class OrgCoreForm(FlaskForm):
    legal_name = StringField(
        "Organization Legal Name",
        validators=[
            DataRequired(message="Legal Name is required"),
            Length(max=120),
        ],
    )

    dba_name = StringField(
        "Doing Business As Alias",
        validators=[Optional(), Length(max=120)],
    )

    ein = StringField(
        "EIN Tax Number",
        validators=[Optional(), Length(max=9)],
    )

    def validate_ein(self, field) -> None:
        raw = (field.data or "").strip()
        if not raw:
            return
        if (not raw.isdigit()) or len(raw) != 9:
            raise ValidationError("EIN must be exactly nine (9) digits")


class ContactForm(FlaskForm):
    # Uses WTF built-in Email validator
    email = EmailField(
        "e-mail",
        validators=[Optional(), Email()],
    )

    # Match simple 10-digit formats like 123-456-7890 or 1234567890
    phone = StringField(
        "Phone",
        validators=[
            Optional(),
            Regexp(
                r"^\d{3}-?\d{3}-?\d{4}$",
                message="Enter a valid 10-digit phone number.",
            ),
        ],
    )

    # If checked (True) = Primary, if unchecked (False) = Secondary
    is_primary = BooleanField("Mark as Primary", default=False)


class AddressForm(FlaskForm):
    # If checked (True) = Physical, if unchecked (False) = Secondary
    is_physical = BooleanField("Mark as Physical Address", default=False)

    # If checked (True) = Postal, if unchecked (False) = Secondary
    is_postal = BooleanField("Mark as Mailing Address", default=False)

    address1 = StringField(
        "PO box or Street address",
        validators=[
            DataRequired(message="First address line required"),
            Length(max=80),
        ],
    )

    address2 = StringField(
        "Apt, Suite number.",
        validators=[
            Optional(),
            Length(max=60),
        ],
    )

    city = StringField(
        "City",
        validators=[
            DataRequired(message="Reqiured field"),
            Length(max=60),
        ],
    )

    # Pattern explanation:
    # ^\d{5}        -> Starts with exactly 5 digits
    # (-\d{4})?$    -> Optionally ends with a hyphen and 4 digits
    postal_code = StringField(
        "Postal/ZIP Code",
        validators=[
            DataRequired(message="Required Field"),
            Regexp(r"^\d{5}(-\d{4})?$", message="Invalid US ZIP Code."),
        ],
    )
