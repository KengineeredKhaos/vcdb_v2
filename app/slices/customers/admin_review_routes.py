# app/slices/customers/admin_review_routes.py
from __future__ import annotations

from .routes import bp

"""
Customers currently publishes advisory-only Admin cues.

Those cues launch back into existing read-only customer surfaces such as:
- customer overview
- customer history detail

Customers has no dedicated Admin intervention routes at present.
"""

__all__ = ["bp"]
