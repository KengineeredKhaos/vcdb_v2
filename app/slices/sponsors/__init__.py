# app/slices/sponsors/__init__.py
from __future__ import annotations

# Register onboarding wizard routes (same blueprint).
# Import side-effect only.
from . import (
    admin_review_routes,  # noqa: F401
    onboard_routes,  # noqa: F401
)
from .routes import bp
from .routes_funding import bp_funding

__all__ = ["bp", "bp_funding", "onboard_routes", "admin_review_routes"]
