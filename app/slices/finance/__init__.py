# app/slices/transactions/__init__.py
from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "finance",
    __name__,
    template_folder="templates",
    url_prefix="/finance",
)
pass
