# app/slices/admin/forms.py
"""
VCDB v2 — Admin slice forms
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import HiddenField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class PolicyEditForm(FlaskForm):
    policy_text = TextAreaField(
        "Policy JSON",
        validators=[DataRequired()],
        render_kw={"rows": 28, "spellcheck": "false"},
    )
    base_hash = HiddenField(
        "Base hash",
        validators=[DataRequired()],
    )
    proposed_hash = HiddenField("Proposed hash")
    reason = StringField(
        "Reason for change",
        validators=[Optional(), Length(max=240)],
        render_kw={
            "placeholder": (
                "Why is this policy being updated right now?"
            )
        },
    )
    preview = SubmitField("Preview")
    commit = SubmitField("Commit")
