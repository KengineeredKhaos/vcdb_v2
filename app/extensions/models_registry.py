# app/extensions/models_registry.py

"""
Single place to import all slice models so Alembic sees them.
DO NOT add any runtime logic here — imports only.
This list is called

Keep list alphabetized to avoid churn in diffs.
"""
from __future__ import annotations

import importlib
import logging
import os

_loaded = False

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


def import_models():
    # load once guard
    global _loaded
    if _loaded:
        return

    # Cycle through importing module models so metadata is available
    for mod in _MODEL_MODULES:
        importlib.import_module(mod)

    # set the guard to prevent future iteration
    _loaded = True

    # write this iteration to logs
    logging.getLogger("app").info(
        {
            "event": "models_registry.loaded",
            "pid": os.getpid(),
            "db_uri": db_uri,
            "modules": len(_MODEL_MODULES),
        }
    )
