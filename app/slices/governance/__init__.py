# app/slices/governance/__init__.py
from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "governance",
    __name__,
    template_folder="templates",
    url_prefix="/governance",
)
