# app/slices/calendar/forms.py

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import DateField, IntegerField, SelectField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class FundingDemandForm(FlaskForm):
    project_ulid = SelectField(
        "Project",
        choices=[],
        validators=[DataRequired()],
    )

    title = StringField(
        "Funding demand title",
        validators=[DataRequired(), Length(max=120)],
    )

    goal_cents = IntegerField(
        "Goal (cents)",
        validators=[DataRequired(), NumberRange(min=0)],
    )

    deadline_date = DateField(
        "Deadline",
        format="%Y-%m-%d",
        validators=[Optional()],
    )

    spending_class = SelectField(
        "Spending class",
        choices=[],
        validators=[Optional()],
    )

    tag_any = StringField(
        "Tags",
        validators=[Optional(), Length(max=255)],
        description="Comma-separated tags",
    )
