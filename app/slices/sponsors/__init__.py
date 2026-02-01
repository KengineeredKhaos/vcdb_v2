# app/slices/sponsors/__init__.py
# Generated scaffolding — VCDB v2 — 2025-09-22 00:11:24 UTC
from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "sponsors",
    __name__,
    template_folder="templates",
    url_prefix="/sponsors",
)

# Import order matters:
# models first (tables),
# then services (business),
# then routes (bp decorators).
from . import models
from . import services
from . import routes

__all__ = ["bp"]
