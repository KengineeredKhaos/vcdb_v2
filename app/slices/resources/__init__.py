# app/slices/resources/__init__.py
from __future__ import annotations

# Register onboarding wizard routes (same blueprint).
# Import side-effect only.
from . import onboard_routes  # noqa: F401
from .routes import bp

__all__ = ["bp"]
