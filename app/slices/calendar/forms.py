# app/slices/calendar/forms.py

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class BudgetSnapshotForm(FlaskForm):
    snapshot_label = StringField(
        "Snapshot label",
        validators=[Optional(), Length(max=100)],
    )
    scope_summary = StringField(
        "Scope summary",
        validators=[Optional(), Length(max=255)],
    )
    assumptions_note = TextAreaField(
        "Assumptions",
        validators=[Optional(), Length(max=255)],
    )


class BudgetLineForm(FlaskForm):
    task_ulid = SelectField(
        "Task",
        choices=[],
        validators=[Optional()],
    )
    line_kind = StringField(
        "Line kind",
        validators=[DataRequired(), Length(max=32)],
    )
    label = StringField(
        "Label",
        validators=[DataRequired(), Length(max=100)],
    )
    detail = StringField(
        "Detail",
        validators=[Optional(), Length(max=255)],
    )
    basis_qty = IntegerField(
        "Quantity",
        validators=[Optional(), NumberRange(min=0)],
    )
    basis_unit = StringField(
        "Unit",
        validators=[Optional(), Length(max=24)],
    )
    unit_cost_cents = IntegerField(
        "Unit cost (cents)",
        validators=[Optional(), NumberRange(min=0)],
    )
    estimated_total_cents = IntegerField(
        "Estimated total (cents)",
        validators=[DataRequired(), NumberRange(min=0)],
    )
    is_offset = BooleanField("This line is an offset")
    offset_kind = StringField(
        "Offset kind",
        validators=[Optional(), Length(max=32)],
    )
    sort_order = IntegerField(
        "Sort order",
        validators=[Optional(), NumberRange(min=0)],
    )


class DemandDraftForm(FlaskForm):
    snapshot_ulid = HiddenField(
        validators=[DataRequired(), Length(min=26, max=26)]
    )
    title = StringField(
        "Draft title",
        validators=[DataRequired(), Length(max=120)],
    )
    summary = TextAreaField(
        "Summary",
        validators=[Optional(), Length(max=255)],
    )
    scope_summary = StringField(
        "Scope summary",
        validators=[Optional(), Length(max=255)],
    )
    requested_amount_cents = IntegerField(
        "Requested amount (cents)",
        validators=[Optional(), NumberRange(min=0)],
    )
    deadline_date = DateField(
        "Needed by",
        format="%Y-%m-%d",
        validators=[Optional()],
    )
    spending_class_candidate = SelectField(
        "Spending class",
        choices=[],
        validators=[Optional()],
    )
    source_profile_key = StringField(
        "Source profile key",
        validators=[Optional(), Length(max=32)],
    )
    ops_support_planned = BooleanField("Ops support planned")
    tag_any = StringField(
        "Tags",
        validators=[Optional(), Length(max=255)],
        description="Comma-separated tags",
    )
    governance_note = TextAreaField(
        "Governance note",
        validators=[Optional(), Length(max=255)],
    )


class DemandDraftReturnForm(FlaskForm):
    note = TextAreaField(
        "Return note",
        validators=[DataRequired(), Length(max=255)],
    )


class DemandDraftApproveForm(FlaskForm):
    spending_class = SelectField(
        "Approved spending class",
        choices=[],
        validators=[Optional()],
    )
    source_profile_key = StringField(
        "Approved source profile key",
        validators=[Optional(), Length(max=32)],
    )
    tag_any = StringField(
        "Approved tags",
        validators=[Optional(), Length(max=255)],
        description="Comma-separated values",
    )
