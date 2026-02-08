# app/slices/customers/__init__.py
from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "customers",
    __name__,
    template_folder="customers",
    static_folder=None,
    url_prefix="/customers",
)

# Import order matters:
# models first (tables),
# then services (business),
# then routes (bp decorators).
from . import models, routes, services

__all__ = ["bp"]
