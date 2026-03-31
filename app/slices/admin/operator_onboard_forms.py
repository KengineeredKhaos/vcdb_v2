from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    HiddenField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
)
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp


class OperatorOnboardForm(FlaskForm):
    first_name = StringField(
        "First name",
        validators=[DataRequired(), Length(max=120)],
    )
    last_name = StringField(
        "Last name",
        validators=[DataRequired(), Length(max=120)],
    )
    preferred_name = StringField(
        "Preferred name",
        validators=[Optional(), Length(max=120)],
    )
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(max=64)],
    )
    email = StringField(
        "Email",
        validators=[
            Optional(),
            Length(max=255),
            Regexp(
                r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                message="Enter a valid email address.",
            ),
        ],
    )
    temporary_password = PasswordField(
        "Temporary password",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    role_code = SelectField(
        "RBAC role",
        validators=[DataRequired()],
        choices=[],
    )
    review = SubmitField("Review")


class OperatorOnboardCommitForm(FlaskForm):
    preview_token = HiddenField(
        "Preview token",
        validators=[DataRequired()],
    )
    commit = SubmitField("Create operator")


class OperatorRbacRoleEditForm(FlaskForm):
    role_code = SelectField(
        "RBAC role",
        validators=[DataRequired()],
        choices=[],
    )
    save = SubmitField("Save RBAC role")
