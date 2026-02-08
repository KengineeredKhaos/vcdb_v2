# app/slices/resources/__init__.py
"""
Resources slice package.

Important:
- bp MUST be registered by the app factory.
- routes MUST be imported so decorators attach to bp.

URL prefix is kept at root (/resources) to match the existing test suite
and the Customers slice pattern (/customers).
"""

from flask import Blueprint

bp = Blueprint("resources", __name__, url_prefix="/resources")

# Import order matters:
# models first (tables),
# then services (business),
# then routes (bp decorators).
from . import (
    models,  # noqa: E402, F401
    routes,  # noqa: F401
    services,  # noqa: F401
)

__all__ = ["bp"]
