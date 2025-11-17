# app/slices/governance/forms.py
# -*- coding: utf-8 -*-
# Governance Admin Forms — skinny forms, JSON validated in-form

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SubmitField, TextAreaField
from wtforms.validators import DataRequired

from app.lib.jsonutil import try_parse_json


class PolicyEditForm(FlaskForm):
    value_json = TextAreaField(
        "Policy JSON (normalized object)", validators=[DataRequired()]
    )
    submit = SubmitField("Save Policy")

    def parsed_value(self):
        """Return parsed JSON dict or raise ValueError for the route to handle."""
        data = self.value_json.data or ""
        obj = try_parse_json(data)
        if not isinstance(obj, dict):
            raise ValueError("Policy value must be a JSON object")
        return obj
