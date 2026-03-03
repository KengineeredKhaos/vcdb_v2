# app/extensions/models_registry.py

# Single place to import all slice models so Alembic sees them.
# DO NOT add any runtime logic here — imports only.
# Keep list alphabetized to avoid churn in diffs.

from __future__ import annotations

import importlib

_MODEL_MODULES: tuple[str, ...] = (
    "app.slices.admin.models",
    "app.slices.attachments.models",
    "app.slices.auth.models",
    "app.slices.calendar.models",
    "app.slices.customers.models",
    "app.slices.entity.models",
    "app.slices.finance.models",
    "app.slices.governance.models",
    "app.slices.ledger.models",
    "app.slices.logistics.models",
    "app.slices.resources.models",
    "app.slices.sponsors.models",
)


def import_models() -> None:
    for mod in _MODEL_MODULES:
        importlib.import_module(mod)
