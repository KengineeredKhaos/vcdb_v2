# app/slices/resources/__init__.py
from __future__ import annotations

from . import (
    admin_issue_routes,  # noqa: F401
    onboard_routes,  # noqa: F401
)
from .routes import bp

__all__ = ["bp"]
