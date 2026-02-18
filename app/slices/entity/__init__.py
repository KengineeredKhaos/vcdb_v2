# app/slices/entity/__init__.py
from __future__ import annotations

from . import routes_wizard  # noqa: F401  (registers wizard routes)
from .routes import bp  # defines bp + basic routes

__all__ = ["bp"]
