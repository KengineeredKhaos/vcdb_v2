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

from . import models, routes  # noqa: E402,F401
