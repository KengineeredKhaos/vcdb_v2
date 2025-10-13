# app/slices/resources/__init__.py
from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "resources",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/resources",
)


# Ensure models import so metadata is registered
from . import models, routes  # noqa: E402,F401
