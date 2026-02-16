# app/slices/entity/errors_wizard.py

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class WizardError(Exception):
    code: str
    user_message: str
    field_errors: Mapping[str, str] | None = None


class WizardNotFound(WizardError):
    pass


class WizardInvalidInput(WizardError):
    pass


class WizardStateConflict(WizardError):
    pass
